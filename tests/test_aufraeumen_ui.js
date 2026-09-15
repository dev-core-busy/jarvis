#!/usr/bin/env node
/**
 * Waechter fuer die Oberflaeche von "Erlerntes Wissen aufraeumen".
 *
 * Gemessen wird das, worauf die Bestaetigung beruht:
 *  - der Vergleich zeigt WIRKLICH die Unterschiede (Diff ausgefuehrt),
 *  - der vom Menschen BEARBEITETE Text gewinnt gegen den Vorschlag,
 *  - abgewaehlte Dateien werden nicht geschickt,
 *  - Fremdtext (Begruendung, Dateiname) wird maskiert.
 */
const fs = require('fs'), path = require('path');
const { JSDOM } = require('jsdom');
const REPO = path.resolve(__dirname, '..');
let OK = 0, FAIL = 0;
const check = (n, b) => { console.log((b ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + n); b ? OK++ : FAIL++; };

const wachhund = setTimeout(() => {
    console.log('\x1b[31mABBRUCH: Zeitlimit\x1b[0m'); process.exit(1);
}, 60000);

(async () => {
const dom = new JSDOM(`<body>
  <div id="kb-cleanup-modal" style="display:none;"></div>
  <div id="kb-cleanup-body"></div>
  <button id="kb-cleanup-apply" style="display:none;"></button>
</body>`, { url: 'https://x/', runScripts: 'outside-only' });
global.window = dom.window; global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
// ⚠ DIE ECHTEN TEXTE, keine Attrappe: nur so faellt ein fehlender Schluessel
// auf, und nur so wirken die Platzhalter ({n}, {q}, {r}), auf denen die
// Anzeige beruht.
require(path.join(REPO, 'frontend/js/i18n.js'));
if (typeof window.setLang === 'function') window.setLang('de');
check('die echten Texte sind geladen (kein Schluessel als Text)',
      window.t('knowledge.cleanup.take') !== 'knowledge.cleanup.take');
window.confirm = () => true;
// Im Browser ist confirm global - im eval-Kontext von Node nicht.
global.confirm = () => true;
// ⚠ DASSELBE FUER `Event`, und hier ist es kein Formfehler: der Renderer baut
// `new Event('input', …)` ohne window-Praefix (Projekt-Idiom, siehe
// pwreveal.js/tabfill.js/prompt_check.js). Node hat ein EIGENES globales Event,
// und jsdom lehnt das mit "parameter 1 is not of type 'Event'" ab - der Handler
// bricht mitten drin ab, der Knopf bleibt gesperrt, und der Waechter meldet
// einen Fehler, den es im Browser nicht gibt (dort ist Event === window.Event).
global.Event = dom.window.Event;

// Den ECHTEN Renderer laden - nicht nachbauen.
const quelle = fs.readFileSync(path.join(REPO, 'frontend/js/knowledge.js'), 'utf8');
function methode(name) {
    // ⚠ 'async' MITNEHMEN: cleanupUebernehmen ist async - ein Muster ohne
    // dieses Wort findet die Methode nicht, und der zusammengesetzte
    // Objektliteral bricht mit "Unexpected token ','".
    let i = quelle.indexOf(`\n    async ${name}(`);
    if (i < 0) i = quelle.indexOf(`\n    ${name}(`);
    if (i < 0) return '';
    let tiefe = 0, j = quelle.indexOf('{', i);
    for (let k = j; k < quelle.length; k++) {
        if (quelle[k] === '{') tiefe++;
        else if (quelle[k] === '}') { tiefe--; if (!tiefe) return quelle.slice(i, k + 1); }
    }
    return '';
}
const teile = ['_diffZeilen', '_cleanupVergleich', '_escHtml', 'cleanupBearbeiten',
               'cleanupUebernehmen', '_fehlertext', '_bilanzHtml', 'cleanupBilanz',
               'cleanupKonflikte', 'cleanupOeffnen', 'cleanupSchliessen',
               '_cleanupListe', '_cleanupZaehler', 'cleanupEinzelSpeichern',
               '_clStatus', 'cleanupAnalysieren', '_cleanupAuswahlVerdrahten',
               '_cleanupAnweisungVerdrahten', 'cleanupMitAnweisung',
               '_anwVorlagen'].map(methode);
check('alle Bausteine geschnitten', teile.every(t => t.length > 20));

const gesendet = [];
const nurApply = () => gesendet.filter(g => /\/apply$/.test(g.url));
// ⚠ AUCH GLOBAL: der Code ruft fetch() ohne window-Praefix, und Node 20 hat
// ein eigenes globales fetch. Ohne diese Zeile ging der Aufruf ins echte Netz,
// landete im catch - und der Test mass eine Kette, die nie stattfand.
const _fetch = async (url, opt) => {
    gesendet.push({ url, body: JSON.parse((opt && opt.body) || '{}') });
    return { ok: true, json: async () => ({ ok: true, erledigt: [], fehler: [], hinweis: '' }) };
};
window.fetch = _fetch; global.fetch = _fetch;
const M = eval(`({ ${teile.join(',\n')} })`);
M._showNotification = () => {};

console.log('\n\x1b[1m1. Der Vergleich zeigt die Unterschiede\x1b[0m');
const d = M._diffZeilen('a\nb\nc\n', 'a\nc\n');
check('Diff laeuft', Array.isArray(d));
check('unveraenderte Zeilen bleiben "gleich"',
      d.filter(x => x[0] === 'gleich').map(x => x[1]).join(',') === 'a,c,');
check('die entfallene Zeile wird als "weg" markiert',
      d.some(x => x[0] === 'weg' && x[1] === 'b'));
check('nichts wird faelschlich als "neu" markiert', !d.some(x => x[0] === 'neu'));
const d2 = M._diffZeilen('x\n', 'x\ny\n');
check('eine hinzugekommene Zeile wird als "neu" markiert',
      d2.some(x => x[0] === 'neu' && x[1] === 'y'));
check('sehr grosse Dateien liefern keinen Diff (Browser-Schutz)',
      M._diffZeilen('z\n'.repeat(2100), 'z\n'.repeat(2100)) === null);

console.log('\n\x1b[1m2. Der Vergleich wird gezeichnet\x1b[0m');
M._cleanupVorschlaege = [
  { schluessel: 'anweisung:style.md', ok: true, geaendert: true,
    alt: 'Antworte kurz.\nAntworte kurz.\n', neu: 'Antworte kurz.\n',
    begruendung: '<img src=x onerror=alert(1)>Dopplung',
    funde: [{ art: 'dopplung', text: 'zweimal' }], fehler: '',
    bytes_alt: 30, bytes_neu: 15 },
  { schluessel: 'anweisung:soul.md', ok: true, geaendert: false,
    alt: 'x', neu: 'x', begruendung: '', funde: [], bytes_alt: 1, bytes_neu: 1 },
  { schluessel: 'gedaechtnis:m.json', ok: false, fehler: 'Zu gross' },
];
M._cleanupVergleich('testmodell');
const body = document.getElementById('kb-cleanup-body');
check('drei Karten gezeichnet', body.querySelectorAll('.kb-cl-karte').length === 3);
check('nur die aenderbare traegt ein Uebernehmen-Kaestchen',
      body.querySelectorAll('.kb-cl-take').length === 1);
check('der Diff steht im DOM', body.querySelectorAll('.kb-cl-diff .dw').length === 1);
check('⚠ Fremdtext wird maskiert (kein Element aus der Begruendung)',
      body.querySelector('img') === null && body.innerHTML.includes('&lt;img'));
check('der Uebernehmen-Knopf erscheint mit Anzahl',
      document.getElementById('kb-cleanup-apply').style.display !== 'none');
check('ein Fehlerfall wird als solcher gezeigt',
      body.querySelectorAll('.kb-cl-karte.ist-fehler').length === 1);

console.log('\n\x1b[1m3. Der Mensch hat das letzte Wort\x1b[0m');
await M.cleanupUebernehmen();
check('genau eine Aenderung geschickt',
      nurApply().length === 1 && nurApply()[0].body.aenderungen.length === 1);
check('und zwar die richtige Datei',
      (nurApply()[0] || {}).body.aenderungen[0].schluessel === 'anweisung:style.md');
check('der Vorschlag wird uebernommen, wenn nichts bearbeitet wurde',
      nurApply()[0].body.aenderungen[0].neu === 'Antworte kurz.\n');
check('⚠ die Bilanz wird mit den Vorschlaegen abgefragt (Vorher/Nachher)',
      gesendet.some(g => /\/prompt$/.test(g.url) && g.body.neu
                    && g.body.neu['anweisung:style.md']));

// Jetzt bearbeiten und abwaehlen
gesendet.length = 0;
M._cleanupVergleich('testmodell');
document.getElementById('kb-cl-edit-0').value = 'VOM MENSCHEN GEAENDERT\n';
await M.cleanupUebernehmen();
check('⚠ der BEARBEITETE Text gewinnt gegen den Vorschlag',
      (nurApply()[0] || {}).body.aenderungen[0].neu === 'VOM MENSCHEN GEAENDERT\n');

gesendet.length = 0;
M._cleanupVergleich('testmodell');
body.querySelector('.kb-cl-take').checked = false;
await M.cleanupUebernehmen();
check('⚠ eine abgewaehlte Datei wird NICHT geschickt', nurApply().length === 0);

console.log('\n\x1b[1m4. Bilanz: was je Anfrage rausgeht\x1b[0m');
const B = { ok: true, basis: 21725, anweisungen: 28505, anweisungen_neu: 24405,
            werkzeuge_bytes: 34553, werkzeuge_anzahl: 85,
            summe: 84783, summe_neu: 80683, token_summe: 23551, token_summe_neu: 22412,
            zeichen_je_token: 3.6, hinweis: '',
            werkzeuge: [{ name: 'gross_tool', bytes: 4200, beschreibung: 900 }] };
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(B, false);
let t = document.getElementById('kb-cleanup-body').textContent;
check('die Gesamtsumme steht da', t.includes('84.783') || t.includes('84,783'));
check('die Token sind als Schaetzung ausgewiesen', /Token/.test(t));
check('der Basis-Prompt wird als nicht aenderbar benannt', /Programmcode/.test(t));
check('die groessten Werkzeuge werden genannt', t.includes('gross_tool'));

document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(B, true);
t = document.getElementById('kb-cleanup-body').textContent;
check('⚠ mit Vergleich steht die ERSPARNIS da (nicht nur die neue Zahl)',
      /−4\.?100|−4,100/.test(t) && (t.includes('80.683') || t.includes('80,683')));

console.log('\n\x1b[1m5. Konfliktansicht\x1b[0m');
// ⚠ DREI ENDPUNKTE, drei Antworten: der Ablauf ist zweistufig geworden
// (Quellen -> Regeln je Haeppchen -> Abgleich). Eine Attrappe, die ueberall
// dasselbe liefert, bildet ihn nicht ab.
const quellenListe = ['BASIS', 'soul.md', 'style.md', 'tools.md',
                      'agents.md', 'user.md', 'identity.md', 'reflection.md'];
const geholt = [];
window.fetch = global.fetch = async (url, opt) => {
    geholt.push(url);
    if (/\/quellen$/.test(url))
        return { ok: true, json: async () => ({ ok: true,
            quellen: quellenListe.map(n => ({ name: n, bytes: 100, referenz: n === 'BASIS' })) }) };
    if (/\/regeln$/.test(url)) {
        const q = JSON.parse(opt.body).quellen;
        return { ok: true, json: async () => ({ ok: true,
            zeilen: q.flatMap(n => [`[${n}] Regel eins.`, `[${n}] Regel zwei.`]) }) };
    }
    return { ok: true, json: async () => ({
        ok: true, regeln: 63, hinweis: 'H',
        konflikte: [{ art: 'widerspruch', quellen: ['style.md', 'tools.md'],
                      regel_a: 'Antworte knapp.', regel_b: 'Begruende ausfuehrlich.',
                      was_tun: 'In style.md praezisieren.' },
                    { art: 'uebersteuerung', quellen: ['BASIS', 'soul.md'],
                      regel_a: 'Nutze immer Werkzeug X.', regel_b: 'Nutze nie Werkzeug X.',
                      was_tun: 'soul.md anpassen - BASIS steht im Code.' }],
        aehnlich: [{ quellen: ['agents.md', 'soul.md'],
                     regel_a: 'Frage nicht um Erlaubnis fuer Standardoperationen.',
                     regel_b: 'Frage nicht nach Erlaubnis fuer offensichtliche Handlungen.' }] }) };
};
document.getElementById('kb-cleanup-body').innerHTML = '<div id="kb-cl-status"></div>';
await M.cleanupKonflikte();
const kb = document.getElementById('kb-cleanup-body');
// Die BEURTEILTEN Karten - nicht alle: die gemessenen kommen weiter unten dazu.
check('beide Konflikte gezeichnet',
      kb.querySelectorAll('.kb-cl-karte:not(.kb-cl-gemessen)').length === 2);
check('Widerspruch und Uebersteuerung sind hervorgehoben',
      kb.querySelectorAll('.kb-cl-karte.ist-warn').length === 2);
check('beide Regeln stehen nebeneinander',
      kb.textContent.includes('Antworte knapp.') && kb.textContent.includes('Begruende ausfuehrlich.'));
check('es steht dabei, was zu tun ist', kb.textContent.includes('In style.md praezisieren.'));
check('die Zahl der Quellen und Regeln wird genannt',
      kb.textContent.includes('8') && kb.textContent.includes('63'));
check('⚠ die Regeln werden in Haeppchen geholt (kein Zehn-Minuten-Request)',
      geholt.filter(u => /\/regeln$/.test(u)).length >= 4);
check('und der Abgleich laeuft genau einmal',
      geholt.filter(u => /\/abgleich$/.test(u)).length === 1);
check('der Uebernehmen-Knopf ist in dieser Ansicht aus',
      document.getElementById('kb-cleanup-apply').style.display === 'none');

// ⚠ GEMESSEN gegen BEURTEILT - die Trennung ist die Aussage der Anzeige.
// Das Modell antwortete auf dieselben 190 Regeln 3 / 0 / 3; die wortaehnlichen
// Paare stehen bei jedem Lauf gleich da und muessen deshalb auch dann
// erscheinen, wenn das Modell nichts meldet.
check('die gemessenen Paare stehen zusaetzlich da',
      kb.querySelectorAll('.kb-cl-karte.kb-cl-gemessen').length === 1);
check('sie stehen NICHT unter den beurteilten Konflikten',
      kb.querySelectorAll('.kb-cl-karte.ist-warn.kb-cl-gemessen').length === 0);
check('ihr Inhalt ist da', kb.textContent.includes('offensichtliche Handlungen'));
check('und die Anzeige sagt, dass sie gemessen sind',
      /gemessen|measured/i.test(kb.textContent));

// Der gefaehrlichste Zustand: Modell meldet NICHTS, es gibt aber messbare Paare.
window.fetch = async (url, opt) => {
    geholt.push(url);
    if (/\/quellen$/.test(url))
        return { ok: true, json: async () => ({ ok: true,
            quellen: quellenListe.map(n => ({ name: n, bytes: 100, referenz: n === 'BASIS' })) }) };
    if (/\/regeln$/.test(url))
        return { ok: true, json: async () => ({ ok: true, zeilen: ['[a.md] Regel.'] }) };
    return { ok: true, json: async () => ({ ok: true, regeln: 190, hinweis: 'H',
        konflikte: [],
        aehnlich: [{ quellen: ['agents.md', 'soul.md'], regel_a: 'A', regel_b: 'B' }] }) };
};
document.getElementById('kb-cleanup-body').innerHTML = '<div id="kb-cl-status"></div>';
await M.cleanupKonflikte();
const kb2 = document.getElementById('kb-cleanup-body');
check('⚠ bei 0 Konflikten bleiben die gemessenen Paare sichtbar',
      kb2.querySelectorAll('.kb-cl-karte.kb-cl-gemessen').length === 1);

// ═══ 6. Das Fenster geht WIRKLICH auf ═══════════════════════════════════════
// ⚠ GEMELDET: "ein Klick darauf macht genau NICHTS". Ursache war
// modal.style.display='flex' - .modal traegt aber opacity:0, sichtbar macht
// erst .open (mit !important). Das Fenster ging damit UNSICHTBAR auf und lag
// als durchsichtige Vollbildschicht ueber der Seite (inset:0, z-index 10001),
// die jeden weiteren Klick schluckte.
//
// GEMESSEN WIRD DIE EIGENSCHAFT, nicht der Aufruf: das echte style.css wird
// geladen und die WIRKSAME Deckkraft abgefragt. Eine Suche nach
// "classList.add('open')" waere gruen, sobald jemand wieder auf display
// umstellt - und der Fehler war ja gerade, dass display allein nicht genuegt.
console.log('\n\x1b[1m6. Fenster oeffnet sichtbar\x1b[0m');
// ⚠ GEZIELT DIE .modal-REGELN, nicht die ganze style.css: als ein einziges
// <style> mit ueber 100 KB kaskadiert jsdom sie nicht mehr - die
// Positivkontrolle unten hat genau das aufgedeckt.
const CSS = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8');
const bloecke = (CSS.match(/\.modal\s*\{[^}]*\}/) || [''])[0]
              + (CSS.match(/\.modal\.open\s*\{[^}]*\}/) || [''])[0];
const stil = document.createElement('style');
stil.textContent = bloecke;
document.head.appendChild(stil);
check('Positivkontrolle: beide .modal-Regeln geschnitten',
      /opacity:\s*0/.test(bloecke) && /opacity:\s*1\s*!important/.test(bloecke));
// ⚠ DAS ECHTE MARKUP, nicht das nachgebaute: der Platzhalter oben im Test-DOM
// traegt KEIN class="modal" - damit griff keine einzige CSS-Regel, und die
// Messung haette ihre eigene Annahme geprueft statt der Seite. (Register: ein
// UI-Test, der sein Markup selbst schreibt, prueft seine eigene Annahme.)
const HTML = fs.readFileSync(path.join(REPO, 'frontend/settings.html'), 'utf8');
const tag = (HTML.match(/<div id="kb-cleanup-modal"[^>]*>/) || [''])[0];
check('Positivkontrolle: das echte Modal-Markup gefunden', tag.length > 20);
check('⚠ es traegt die Klasse "modal" (sonst greift keine Regel)',
      /class="[^"]*\bmodal\b/.test(tag));
const alt_el = document.getElementById('kb-cleanup-modal');
const echt = document.createElement('div');
echt.innerHTML = tag + '</div>';
alt_el.replaceWith(echt.firstElementChild);
const modal = document.getElementById('kb-cleanup-modal');
const sicht = () => {
    const c = window.getComputedStyle(modal);
    return { d: c.display, o: parseFloat(c.opacity || '1') };
};
const zu = sicht();
check('vor dem Klick ist das Fenster zu', zu.d === 'none');
// Positivkontrolle: greift das echte CSS in dieser Umgebung ueberhaupt?
check('Positivkontrolle: das echte style.css wirkt (opacity 0 im Ruhezustand)',
      zu.o === 0);
window.fetch = async () => ({ ok: true, json: async () => ({ ok: true, dateien: [] }) });
await M.cleanupOeffnen();
const auf = sicht();
check('nach dem Klick ist es sichtbar (display)', auf.d === 'flex');
check('⚠ UND deckend - sonst liegt es unsichtbar ueber der Seite',
      auf.o > 0.9);
M.cleanupSchliessen();
check('Schliessen macht es wieder unsichtbar', sicht().d === 'none');

// ⚠ REGEL statt Messung - und zwar aus einem gemessenen Grund: jsdom bildet
// "Inline gegen !important" anders ab als ein Browser. Ein
// modal.style.display='none' sieht hier wie geschlossen aus, waehrend
// .modal.open{display:flex !important} es im echten Browser OFFEN liesse.
// Deshalb wird das Modal ausschliesslich ueber die Klasse gesteuert.
const KJS = fs.readFileSync(path.join(REPO, 'frontend/js/knowledge.js'), 'utf8')
              .replace(/^\s*\/\/.*$/gm, '');
check('Positivkontrolle: der Kommentar-Filter hat gearbeitet',
      KJS.includes('cleanupOeffnen') && !KJS.includes('UEBER DIE KLASSE'));
const stellen = (KJS.match(/kb-cleanup-modal[\s\S]{0,260}/g) || []);
check('kein style.display auf dem Aufraeum-Fenster',
      stellen.every(b => !/\bstyle\.display\s*=/.test(b.split('classList')[0])));
check('es wird ueber classList mit "open" gesteuert',
      /classList\.add\('open'\)/.test(KJS) && /classList\.remove\('open'\)/.test(KJS));

console.log('\n\x1b[1m7. Einzelnes Speichern - der Knopf neben dem Stift\x1b[0m');
// ⚠ EIGENER FETCH MIT ECHTER ERFOLGSANTWORT: die Attrappe oben liefert
// erledigt:[] - damit waere "die Sicherung steht an der Karte" gar nicht
// messbar, und der Test pruefte eine Kette, die es so nicht gibt.
const einzeln = [];
let applyFehler = null;
const applyFetch = async (url, opt) => {
    const body = JSON.parse((opt && opt.body) || '{}');
    einzeln.push({ url, body });
    if (/\/apply$/.test(url)) {
        const k = (body.aenderungen || [])[0] || {};
        if (applyFehler) return { ok: true, json: async () => ({
            ok: false, erledigt: [], fehler: [{ schluessel: k.schluessel, fehler: applyFehler }] }) };
        return { ok: true, json: async () => ({ ok: true, hinweis: '',
            erledigt: [{ schluessel: k.schluessel, sicherung: 'style.md.bak-20260906' }], fehler: [] }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
};
window.fetch = applyFetch; global.fetch = applyFetch;

// ZWEI aenderbare Karten - sonst laesst sich ein Dekrement nicht von
// "verschwindet ganz" unterscheiden.
M._cleanupVorschlaege = [
  { schluessel: 'anweisung:style.md', ok: true, geaendert: true,
    alt: 'A\nA\n', neu: 'A\n', begruendung: '', funde: [], bytes_alt: 4, bytes_neu: 2 },
  { schluessel: 'anweisung:tools.md', ok: true, geaendert: true,
    alt: 'B\nB\n', neu: 'B\n', begruendung: '', funde: [], bytes_alt: 4, bytes_neu: 2 },
];
M._cleanupVergleich('testmodell');
const zaehlText = () => document.getElementById('kb-cleanup-apply').textContent;
check('jede aenderbare Karte traegt einen Speichern-Knopf',
      document.querySelectorAll('.kb-cl-save').length === 2);
const einKnopf = () => document.querySelector('.kb-cl-save') || document.createElement('i');
check('der Speichern-Knopf ist beschriftet (kein leeres Symbol)',
      (einKnopf().textContent || '').trim().length > 2);
check('der Speichern-Knopf sagt im title, was er tut',
      /Datei/.test(einKnopf().getAttribute('title') || ''));
check('der Zaehler unten nennt zu Beginn beide', /\b2\b/.test(zaehlText()));

// Der bearbeitete Text muss auch auf diesem Weg gewinnen.
einzeln.length = 0;
document.getElementById('kb-cl-edit-0').value = 'VOM MENSCHEN\n';
await M.cleanupEinzelSpeichern(0, document.querySelector('.kb-cl-save') || undefined);
const ea = einzeln.filter(g => /\/apply$/.test(g.url));
// ⚠ Nie ungeprueft dereferenzieren: bei ausgebautem Fix ist die Liste leer,
// und ein ea[0].body WIRFT - die Gegenprobe braeche dann ab statt fehlzuschlagen.
const e1 = (ea[0] || { body: { aenderungen: [] } }).body.aenderungen || [];
check('genau EIN Schreibaufruf', ea.length === 1);
check('und darin genau EINE Datei - nicht der ganze Stapel', e1.length === 1);
check('und zwar die angeklickte', (e1[0] || {}).schluessel === 'anweisung:style.md');
check('⚠ der BEARBEITETE Text gewinnt auch beim Einzelspeichern',
      (e1[0] || {}).neu === 'VOM MENSCHEN\n');

// ─── DAS IST DIE EIGENTLICHE FORDERUNG ───
check('⚠ der Zaehler unten geht um eins zurueck', /\b1\b/.test(zaehlText()));
const k0 = document.getElementById('kb-cl-karte-0');
check('die gespeicherte Karte ist als erledigt gekennzeichnet',
      k0.classList.contains('ist-fertig'));
check('⚠ ihr Uebernehmen-Kaestchen ist weg (sonst schreibt der Sammelknopf sie erneut)',
      k0.querySelector('.kb-cl-take') === null);
check('ihr Speichern-Knopf ist weg (ein zweiter Klick waere sinnlos)',
      k0.querySelector('.kb-cl-save') === null);
const st0 = document.getElementById('kb-cl-stat-0');
check('die Karte sagt "gespeichert" - als WORT, nicht nur als Farbe',
      !st0.hidden && st0.textContent.includes(window.t('knowledge.cleanup.saved')));
check('und nennt die Sicherung', st0.textContent.includes('style.md.bak-20260906'));

// Der Sammelweg darf die bereits geschriebene Datei nicht noch einmal schicken.
einzeln.length = 0;
await M.cleanupUebernehmen();
const sa = einzeln.filter(g => /\/apply$/.test(g.url));
const s1 = ((sa[0] || { body: {} }).body.aenderungen) || [];
check('der Sammelknopf schickt danach nur noch die uebrige Datei',
      sa.length === 1 && s1.length === 1
      && (s1[0] || {}).schluessel === 'anweisung:tools.md');

console.log('\n\x1b[1m7b. Fehlschlag: nichts wird als erledigt behauptet\x1b[0m');
M._cleanupVergleich('testmodell');
applyFehler = 'Kein gueltiges JSON';
einzeln.length = 0;
const knopf1 = document.querySelector('#kb-cl-karte-1 .kb-cl-save')
             || document.createElement('button');
await M.cleanupEinzelSpeichern(1, knopf1);
check('die Karte bleibt offen (Kaestchen noch da)',
      document.querySelector('#kb-cl-karte-1 .kb-cl-take') !== null);
check('⚠ der Zaehler sinkt NICHT bei einem Fehlschlag', /\b2\b/.test(zaehlText()));
check('der Grund steht an der Karte',
      document.getElementById('kb-cl-stat-1').textContent.includes('Kein gueltiges JSON'));
check('der Knopf ist wieder bedienbar (zweiter Versuch moeglich)',
      knopf1.disabled === false);
applyFehler = null;

console.log('\n\x1b[1m7c. Abwaehlen zaehlt ebenfalls herunter\x1b[0m');
M._cleanupVergleich('testmodell');
check('Positivkontrolle: zwei offen', /\b2\b/.test(zaehlText()));
const kast = document.querySelector('.kb-cl-take');
kast.checked = false;
kast.dispatchEvent(new window.Event('change', { bubbles: true }));
check('⚠ der Knopf nennt nur noch, was er wirklich schreiben wuerde',
      /\b1\b/.test(zaehlText()));
kast.checked = true;
kast.dispatchEvent(new window.Event('change', { bubbles: true }));
check('und wieder hoch beim Anwaehlen', /\b2\b/.test(zaehlText()));

console.log('\n\x1b[1m7d. Regeln\x1b[0m');
// Der Zaehler wird ABGELEITET, nicht mitgefuehrt: eine mitgefuehrte Zahl
// laeuft beim naechsten Weg (Einzelspeichern, Abwaehlen, kuenftiges Loeschen)
// auseinander und der Knopf behauptet etwas, das er nicht einloest.
check('⚠ der Zaehler wird aus dem DOM abgeleitet',
      /_cleanupZaehler\s*\(\)\s*\{[\s\S]{0,400}querySelectorAll\('\.kb-cl-take:checked'\)/.test(KJS));
check('das Einzelspeichern zieht den Zaehler nach',
      /cleanupEinzelSpeichern[\s\S]*?_cleanupZaehler\(\)/.test(KJS));
check('geschrieben wird ueber denselben Endpunkt wie der Sammelweg',
      (KJS.match(/knowledge\/cleanup\/apply/g) || []).length === 2);
const TXT = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');
check('die neuen Texte gibt es in DE und EN',
      (TXT.match(/'knowledge\.cleanup\.save_one':/g) || []).length === 2
      && (TXT.match(/'knowledge\.cleanup\.saved':/g) || []).length === 2);
check('der Ergebnis-Hinweis erklaert den neuen Knopf',
      /Speichern/.test(window.t('knowledge.cleanup.result_hint')));
const CSS2 = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8');
check('die erledigte Karte hat eigenes CSS', /\.kb-cl-karte\.ist-fertig\s*\{/.test(CSS2));
check('⚠ die Statuszeile ist auch im hellen Thema lesbar (eigener Ton)',
      /body\.light\s+\.kb-cl-karte-status\.ist-gut/.test(CSS2));

console.log('\n\x1b[1m8. Der Knopf in den System-Einstellungen\x1b[0m');
// ⚠ GEMESSEN AM ECHTEN MARKUP: der Knopf steht ZUSAETZLICH unter
// KI & System -> System-Einstellungen. Er ruft DIESELBE Funktion wie der unter
// Wissen - ein zweiter Weg waere eine zweite Stelle zum Pflegen.
const SH = fs.readFileSync(path.join(REPO, 'frontend/settings.html'), 'utf8');
const iTun = SH.indexOf('id="prof-sect-tuning-body"');
const iEnde = SH.indexOf('id="prof-sect-', iTun + 10);
const tuning = SH.slice(iTun, iEnde > 0 ? iEnde : iTun + 20000);
check('Positivkontrolle: der Tuning-Container wurde geschnitten',
      iTun > 0 && tuning.includes('setting-tts-voice'));
check('der Knopf steht IM Container "System-Einstellungen"',
      tuning.includes('id="btn-prompt-optimieren"'));
check('er ruft cleanupOeffnen', /btn-prompt-optimieren[\s\S]{0,300}cleanupOeffnen\(\)/.test(tuning));
// ⚠ GENAU EIN WEG IN DEN DIALOG (Vorgabe 2026-09-06): der frueher unter
// Wissen -> Wissens-Verdichtung erzeugte Knopf ist entfernt. Zwei Wege waeren
// zwei Stellen zum Pflegen - und die Erklaerung, WOFUER man ihn drueckt, gibt
// es nur an der neuen. Gezaehlt werden die OEFFNER, nicht der "Zurueck"-Knopf
// im Dialog selbst.
const KJS2 = fs.readFileSync(path.join(REPO, 'frontend/js/knowledge.js'), 'utf8');
check('⚠ der alte Knopf unter Wissens-Verdichtung ist weg',
      !/id="kb-cleanup-btn"/.test(KJS2));
const oeffner = (SH.match(/cleanupOeffnen\(\)/g) || []).length;
check('im Markup gibt es genau EINEN Oeffner', oeffner === 1);
check('und der i18n-Schluessel des alten Knopfes ist nicht mehr in Benutzung',
      !/knowledge\.cleanup\.btn'/.test(KJS2) && !/knowledge\.cleanup\.btn'/.test(SH));
check('⚠ er prueft vorher, dass es den Manager gibt (sonst wirft der Klick)',
      /knowledgeManager\s*&amp;&amp;\s*window\.knowledgeManager\.cleanupOeffnen/.test(tuning)
      || /knowledgeManager\s*&&\s*window\.knowledgeManager\.cleanupOeffnen/.test(tuning));
check('⚠ eine ERKLAERUNG steht dabei (nicht nur ein Knopf)',
      /class="tuning-hint"[^>]*data-i18n="profile\.prompt_opt_hint"/.test(tuning));
check('Beschriftung und Titel folgen dem Sprachwechsel',
      /data-i18n="knowledge\.cleanup\.btn_short"/.test(tuning)
      && /data-i18n-title="knowledge\.cleanup\.btn_title"/.test(tuning));
const I18N = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');
for (const k of ['knowledge.cleanup.btn_short', 'profile.section_prompt',
                 'profile.prompt_opt_hint']) {
  const n = (I18N.match(new RegExp("'" + k.replace(/\./g, '\\.') + "':", 'g')) || []).length;
  check(`${k} gibt es in DE und EN`, n === 2);
}
check('die Erklaerung nennt, WAS je Anfrage rausgeht',
      /Basis-Prompt/.test(window.t('profile.prompt_opt_hint'))
      && /Werkzeuge/.test(window.t('profile.prompt_opt_hint')));
check('und dass erst nach Bestaetigung geschrieben wird',
      /Bestätigung/.test(window.t('profile.prompt_opt_hint')));
const CSS3 = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8');
check('.tuning-hint ist gestaltet (sonst steht der Satz wie Fliesstext)',
      /\.tuning-hint\s*\{/.test(CSS3));
// Der Manager wird in settings.html geladen - sonst ist der Knopf tot.
check('knowledge.js ist auf der Seite eingebunden',
      /knowledge\.js\?v=\d+/.test(SH));

console.log('\n\x1b[1m8b. Der Klick OEFFNET wirklich (Markup ist kein Beweis)\x1b[0m');
// ⚠ AM 2026-09-05 BEZAHLT: der Knopf sah richtig aus und oeffnete ein
// UNSICHTBARES Fenster, das danach jeden weiteren Klick schluckte. Deshalb
// wird hier der ECHTE Klick ausgefuehrt und die WIRKUNG gemessen.
{
  // ⚠ 'dangerously' IST HIER PFLICHT, nicht Bequemlichkeit: mit
  // 'outside-only' fuehrt jsdom INLINE-onclick NICHT aus (nachgemessen), und
  // der Test meldete einen toten Knopf, den es nicht gibt. Externe <script src>
  // laedt jsdom ohne resources:'usable' ohnehin nicht - es laufen also nur die
  // Inline-Skripte der Seite.
  const dom2 = new JSDOM(SH, { url: 'https://x/', runScripts: 'dangerously' });
  const w2 = dom2.window, d2 = w2.document;
  // Nur die zwei .modal-Regeln - die ganze style.css kaskadiert jsdom nicht.
  const st2 = d2.createElement('style');
  st2.textContent = bloecke;
  d2.head.appendChild(st2);
  // ⚠ Nie ungeprueft dereferenzieren: fehlt der Knopf, WIRFT der Klick weiter
  // unten - die Gegenprobe braeche ab statt fehlzuschlagen, und ein
  // abgebrochener Waechter ist von einem bestandenen nicht zu unterscheiden.
  const knopf = d2.getElementById('btn-prompt-optimieren') || d2.createElement('button');
  check('der Knopf existiert im echten Markup',
        !!d2.getElementById('btn-prompt-optimieren'));
  // Positivkontrolle der MESSMETHODE: fuehrt diese Umgebung Inline-onclick aus?
  // Ohne sie waere ein "der Knopf tut nichts" nicht von einem Testartefakt zu
  // unterscheiden - genau das ist beim Bau passiert.
  const probe = d2.createElement('button');
  probe.setAttribute('onclick', 'window.__probe = 1');
  d2.body.appendChild(probe);
  probe.dispatchEvent(new w2.Event('click', { bubbles: true }));
  check('Positivkontrolle: diese Umgebung fuehrt Inline-onclick aus', w2.__probe === 1);
  const modal2 = d2.getElementById('kb-cleanup-modal');
  const sicht2 = () => {
      const c = w2.getComputedStyle(modal2);
      return { d: c.display, o: parseFloat(c.opacity || '1') };
  };
  check('Positivkontrolle: vorher ist das Fenster unsichtbar',
        sicht2().d === 'none' && sicht2().o === 0);
  // Den echten Oeffner einhaengen (wie knowledge.js ihn bereitstellt).
  let gerufen = 0;
  w2.knowledgeManager = {
      cleanupOeffnen() { gerufen++; modal2.classList.add('open'); },
  };
  // Der Klick laeuft ueber das onclick-Attribut des ECHTEN Markups.
  knopf.dispatchEvent(new w2.Event('click', { bubbles: true }));
  check('⚠ der Klick ruft cleanupOeffnen (kein toter Knopf)', gerufen === 1);
  const auf2 = sicht2();
  check('⚠ und das Fenster ist danach SICHTBAR (display)', auf2.d === 'flex');
  check('⚠ UND DECKEND - sonst liegt es unsichtbar ueber der Seite', auf2.o > 0.9);
  // Ohne Manager darf der Klick nicht werfen (Seite frisch geladen).
  delete w2.knowledgeManager;
  let warf = false;
  try { knopf.dispatchEvent(new w2.Event('click', { bubbles: true })); }
  catch (e) { warf = true; }
  check('⚠ ohne geladenen Manager wirft der Klick NICHT', !warf);
  dom2.window.close();
}

console.log('\n\x1b[1m8c. Die Bilanz sagt, wenn ein Zuschnitt aktiv ist\x1b[0m');
// ⚠ Ein Feld, das nur im Speicher steht, ist keine Aussage (Lehre vom
// 2026-09-02: `soft` lag ein Vierteljahr im Backend und erreichte die
// Oberflaeche nie). Der Zuschnitt macht die Bilanz zur OBERGRENZE - das muss
// dort stehen, sonst haelt der Administrator sie fuer den Regelfall.
const Bz = { ok: true, basis: 21810, anweisungen: 25372, anweisungen_neu: 21575,
             werkzeuge_bytes: 53286, werkzeuge_anzahl: 86, summe: 100468,
             summe_neu: 96671, zeichen_je_token: 3.6, werkzeuge: [] };
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
check('ohne Zuschnitt steht kein Hinweis da',
      !document.querySelector('.kb-cl-zuschnitt'));
Bz.zuschnitt_aktiv = true;
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
const hz = document.querySelector('.kb-cl-zuschnitt');
check('⚠ mit Zuschnitt steht der Hinweis da', !!hz);
check('und er sagt, dass es eine OBERGRENZE ist',
      /OBERGRENZE|Obergrenze/.test((hz && hz.textContent) || ''));
const I18N2 = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');
check('der Text gibt es in DE und EN',
      (I18N2.match(/'knowledge\.cleanup\.b_zuschnitt':/g) || []).length === 2);
// ⚠ VOM BETREIBER GEMELDET (2026-09-06): "gehen bei jeder Anfrage mit - nur im
// Code aenderbar" stimmt seit dem Zuschnitt NICHT mehr. Eine Anzeige, die einen
// Zustand behauptet, den sie nicht kennt - und hier widersprach sie sogar dem
// Hinweis zwei Zeilen darunter. Die Erklaerspalten haengen jetzt am Zuschnitt.
Bz.zuschnitt_aktiv = false;
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
let txtAus = document.getElementById('kb-cleanup-body').textContent;
check('ohne Zuschnitt: "gehen bei jeder Anfrage mit"',
      /bei jeder Anfrage mit/.test(txtAus));
Bz.zuschnitt_aktiv = true;
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
let txtAn = document.getElementById('kb-cleanup-body').textContent;
check('⚠ MIT Zuschnitt steht das NICHT mehr da (es waere falsch)',
      !/bei jeder Anfrage mit/.test(txtAn));
check('⚠ stattdessen: Obergrenze / nur das passende Buendel',
      /Obergrenze/.test(txtAn) && /Bündel/.test(txtAn));
check('auch die Basis-Zeile sagt, dass Abschnitte entfallen',
      /entfallen/.test(txtAn));
check('die vier neuen Texte gibt es in DE und EN',
      (I18N2.match(/'knowledge\.cleanup\.b_wz_note_zu':/g) || []).length === 2
      && (I18N2.match(/'knowledge\.cleanup\.b_basis_note_zu':/g) || []).length === 2);

console.log('\n\x1b[1m8d. Die KOPFZEILE selbst - sie ist die einzige, die man immer sieht\x1b[0m');
// ⚠ ZWEITE MELDUNG DESSELBEN TAGES: "falscher Text hinter 'was bei einer
// Anfrage an das Modell geht' ist doch immer noch bullshit - wir haben doch
// Buendel-Zuschnitt geschaffen?!" Zutreffend. Die Korrektur von 8c hat die
// Meta-Spalten und die Fussnote gefixt - also genau die Teile INNERHALB des
// <details>, und das ist ohne Vergleich ZU. Die eine sichtbare Zeile blieb
// stehen und behauptete weiter den vollen Satz als Ist-Wert.
//
// ⚠ DESHALB WIRD HIER DAS <summary> ISOLIERT GEMESSEN, nicht der textContent
// des ganzen Kastens: "Obergrenze" steht auch in der Meta-Spalte, die Pruefung
// waere darueber trivial wahr und der gemeldete Fehler bliebe gruen.
const summ = () => {
    const d = document.querySelector('.kb-cl-bilanz');
    const sm = d && d.querySelector('summary');
    return (sm && sm.textContent) || '';
};
const detOffen = () => {
    const d = document.querySelector('.kb-cl-bilanz');
    return !!(d && d.hasAttribute('open'));
};
Bz.zuschnitt_aktiv = false;
delete Bz.zuschnitt_min; delete Bz.zuschnitt_max;
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
check('⚠ der Kasten ist im Regelfall ZU - nur das <summary> ist sichtbar',
      !detOffen());
check('ohne Zuschnitt heisst die Kopfzeile wie bisher',
      /Was bei einer Anfrage an das Modell geht/.test(summ()));
Bz.zuschnitt_aktiv = true;
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
check('⚠ MIT Zuschnitt behauptet die Kopfzeile das NICHT mehr',
      !/Was bei einer Anfrage an das Modell geht/.test(summ()));
check('sie nennt die Zahl als Obergrenze', /Obergrenze/.test(summ()));
check('⚠ und ohne gerechnete Spanne behauptet sie KEINE zweite Zahl',
      /Zuschnitt aktiv/.test(summ()) && !/–\s*[\d.]+–/.test(summ()));
Bz.zuschnitt_min = 47110; Bz.zuschnitt_max = 88900;
Bz.zuschnitt_token_min = 13086; Bz.zuschnitt_token_max = 24694;
Bz.zuschnitt_min_thema = 'bild'; Bz.zuschnitt_max_thema = 'dokument';
document.getElementById('kb-cleanup-body').innerHTML = M._bilanzHtml(Bz, false);
const sTxt = summ();
check('⚠ mit gemessener Spanne steht sie DANEBEN, nicht in der Fussnote',
      /47\.?110/.test(sTxt) && /88\.?900/.test(sTxt));
check('und die Obergrenze bleibt trotzdem stehen', /100\.?468/.test(sTxt));
check('die Spanne traegt eine eigene Klasse (gedaempft, nicht fett)',
      !!document.querySelector('.kb-cl-spanne'));
const CSS_SP = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8');
// ⚠ NICHT nur "der Name kommt in einem Selektor vor" - das war die erste
// Fassung, und ihre Gegenprobe biss NICHT: die @media-Regel darunter traegt
// denselben Selektor und haelt das Muster am Leben, obwohl die Basisregel weg
// ist. Gemessen wird die EIGENSCHAFT: gedaempft UND nicht fett, damit die
// Obergrenze davor die Hauptaussage bleibt.
const spBloecke = (CSS_SP.match(/\.kb-cl-spanne\s*\{[^}]*\}/g) || []);
check('und diese Klasse hat CSS: gedaempft und normal gewichtet',
      spBloecke.some(b => /color\s*:/.test(b) && /font-weight\s*:\s*400/.test(b)));
check('die drei neuen Texte gibt es in DE und EN',
      (I18N2.match(/'knowledge\.cleanup\.bilanz_titel_zu':/g) || []).length === 2
      && (I18N2.match(/'knowledge\.cleanup\.bilanz_spanne':/g) || []).length === 2
      && (I18N2.match(/'knowledge\.cleanup\.bilanz_spanne_kurz':/g) || []).length === 2);
// ⚠ Der Hinweistext darunter darf die Spanne NICHT wiederholen - er soll das
// erklaeren, was die Kopfzeile nicht sagt: dass die Anweisungsdateien vom
// Zuschnitt gar nicht profitieren und deshalb in jedem Fall wirken. Genau das
// ist die Aussage, um die es in DIESEM Dialog geht.
const hz2 = document.querySelector('.kb-cl-zuschnitt');
check('der Hinweis darunter erklaert die Anweisungsdateien',
      /Anweisungsdateien/.test((hz2 && hz2.textContent) || ''));

// ─────────────────────────────────────────────────────────────────────────
console.log('\n\x1b[1m9. Waehrend des Laufs dreht sich sichtbar etwas\x1b[0m');
// ⚠ GEMELDET: nach dem Klick auf "Analysieren" stand die Fortschrittszeile
// minutenlang unveraendert da - "arbeitet noch" war von "haengt" nicht zu
// unterscheiden. Gemessen wird deshalb der Zustand WAEHREND des Laufs, nicht
// hinterher: die Attrappe haelt bei jedem Netzabruf fest, was das
// Status-Element in diesem Moment traegt.
document.getElementById('kb-cleanup-body').innerHTML =
    `<label><input type="checkbox" class="kb-cl-sel" value="a" checked></label>
     <label><input type="checkbox" class="kb-cl-sel" value="b" checked></label>
     <button id="kb-cl-start"></button>
     <div id="kb-cl-status" class="kb-hint"></div>`;
const stEl = () => document.getElementById('kb-cl-status');
const waehrend = [];
global.fetch = window.fetch = async (url) => {
    // ⚠ NUR die Analyse-Abrufe zaehlen. Der erste Anlauf nahm jeden fetch mit -
    // auch den Bilanz-Abruf, den _cleanupVergleich NACH dem Lauf macht, wenn
    // der Kasten samt Statuszeile laengst ersetzt ist: die Messung meldete
    // einen Fehler, den es nicht gab.
    if (/\/analyse$/.test(url)) {
        const el = stEl();
        waehrend.push({ text: el ? el.textContent : '', dreht: !!(el && el.classList.contains('kb-cl-laeuft')) });
    }
    return { ok: true, json: async () => ({ modell: 'testmodell', ergebnisse: [] }) };
};
await M.cleanupAnalysieren();
check('der Lauf hat wirklich stattgefunden (Positivkontrolle)', waehrend.length > 0);
check('⚠ waehrend des Laufs traegt die Statuszeile das Laufzeichen',
      waehrend.length > 0 && waehrend.every(w => w.dreht));
check('und der Fortschrittstext steht trotzdem da (Platzhalter ersetzt)',
      waehrend.length > 0 && /\b2 von 2\b/.test(waehrend[0].text)
      && !/\{i\}|\{n\}/.test(waehrend[0].text));
// Nach dem Lauf ersetzt der Vergleich den ganzen Kasten - das Zeichen ist mit
// dem Element weg. Die eigene Zusage bleibt trotzdem pruefbar:
document.getElementById('kb-cleanup-body').innerHTML =
    '<div id="kb-cl-status" class="kb-hint"></div>';
M._clStatus('laeuft', true);
check('_clStatus setzt das Zeichen', stEl().classList.contains('kb-cl-laeuft'));
M._clStatus('fertig', false);
check('⚠ und nimmt es zurueck - ein Zeichen, das nach dem Fehler weiterdreht, luegt',
      !stEl().classList.contains('kb-cl-laeuft') && stEl().textContent === 'fertig');
// Fehlerfall AUSGEFUEHRT: eine abgebrochene Analyse darf nicht weiterdrehen.
global.fetch = window.fetch = async () => ({ ok: false, status: 500, json: async () => ({}), text: async () => 'kaputt' });
document.getElementById('kb-cleanup-body').innerHTML =
    `<label><input type="checkbox" class="kb-cl-sel" value="a" checked></label>
     <button id="kb-cl-start"></button><div id="kb-cl-status" class="kb-hint"></div>`;
await M.cleanupAnalysieren();
check('⚠ nach einem Fehler steht der Grund da und nichts dreht sich mehr',
      !stEl().classList.contains('kb-cl-laeuft') && stEl().textContent.length > 0);
// Ohne Auswahl gibt es keinen Lauf - und damit auch kein Laufzeichen.
document.getElementById('kb-cleanup-body').innerHTML =
    '<button id="kb-cl-start"></button><div id="kb-cl-status" class="kb-hint"></div>';
await M.cleanupAnalysieren();
check('ohne Auswahl dreht sich nichts', !stEl().classList.contains('kb-cl-laeuft'));

// Die EIGENSCHAFT im CSS, nicht das Vorkommen des Namens: es muss wirklich ein
// rotierender Ring entstehen. (Lehre aus .kb-cl-spanne: eine @media-Regel mit
// demselben Selektor haelt ein blosses Namensmuster am Leben.)
const CSS_L = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8');
const ringBlock = (CSS_L.match(/\.kb-cl-laeuft::before\s*\{[^}]*\}/g) || []);
check('⚠ die Klasse erzeugt einen rotierenden Ring (Rundung + Animation)',
      ringBlock.some(b => /border-radius\s*:\s*50%/.test(b)
                       && /animation\s*:\s*spin/.test(b)
                       && /content\s*:/.test(b)));
const basisBlock = (CSS_L.match(/\.kb-cl-laeuft\s*\{[^}]*\}/g) || []);
check('und der Ring steht NEBEN dem Text, nicht darueber',
      basisBlock.some(b => /display\s*:\s*flex/.test(b) && /gap\s*:/.test(b)));
check('bewegungsempfindliche Benutzer bekommen keine Animation',
      /prefers-reduced-motion[\s\S]{0,400}\.kb-cl-laeuft/.test(CSS_L));
// Der Cache-Buster muss mit - sonst behaelt der Browser des Melders genau die
// Fassung ohne Zeichen.
['settings.html', 'wissen.html'].forEach(seite => {
    const h = fs.readFileSync(path.join(REPO, 'frontend', seite), 'utf8');
    check(`${seite}: knowledge.js und style.css sind neu genug`,
          /knowledge\.js\?v=(11[3-9]|1[2-9]\d|[2-9]\d\d)/.test(h)
          && /style\.css\?v=(17[6-9]|1[89]\d|[2-9]\d\d)/.test(h));
});

console.log('\n\x1b[1m10. Eigene Anweisung: Feld, Knopf und was gesendet wird\x1b[0m');
// ⚠ AUSGEFUEHRT, nicht im Quelltext gesucht: ob ein Feld ENTSTEHT, ob der
// Knopf wirklich gesperrt ist und was am Ende im Rumpf landet, kann eine
// Textsuche nicht beantworten.
const bodyEl = document.getElementById('kb-cleanup-body');
M._cleanupDateien = [
    { schluessel: 'anweisung:style.md', art: 'anweisung', name: 'style.md',
      bytes: 900, herkunft: 'geaendert', zu_gross: false },
    { schluessel: 'gedaechtnis:memory.json', art: 'gedaechtnis', name: 'memory.json',
      bytes: 2000, herkunft: 'vom Agenten', zu_gross: false },
];
window.fetch = async () => ({ ok: true, json: async () => ({ ok: true }) });
M._cleanupListe();
const feld = document.getElementById('kb-cl-anw-text');
const anwKnopf = document.getElementById('kb-cl-anw-start');
check('das Eingabefeld wird gezeichnet', !!feld && feld.tagName === 'TEXTAREA');
check('der zweite Knopf steht daneben', !!anwKnopf);
check('das Feld erklaert sich selbst (Platzhalter mit Beispiel)',
      !!feld && (feld.getAttribute('placeholder') || '').length > 20);
check('⚠ der Knopf ist gesperrt, solange nichts drinsteht',
      !!anwKnopf && anwKnopf.disabled === true);
check('und sagt auch, warum (gesperrt MIT Begruendung, nicht verborgen)',
      !!anwKnopf && (anwKnopf.title || '').length > 5 && anwKnopf.offsetParent !== undefined);
// Tippen -> der Knopf wird frei. Ueber das ECHTE Ereignis, nicht per Hand.
feld.value = 'Entferne alle Merksaetze zu Jira.';
feld.dispatchEvent(new window.Event('input'));
check('nach der Eingabe ist er bedienbar', anwKnopf.disabled === false);
check('und der Titel sagt jetzt etwas anderes',
      (anwKnopf.title || '') !== window.t('knowledge.cleanup.anw_btn_leer'));
feld.value = '   ';
feld.dispatchEvent(new window.Event('input'));
check('nur Leerzeichen zaehlen nicht als Anweisung', anwKnopf.disabled === true);

// Was geht wirklich raus?
const gesendet10 = [];
const f10roh = async (url, opt) => {
    gesendet10.push({ url, body: JSON.parse((opt && opt.body) || '{}') });
    if (/\/analyse$/.test(url)) {
        return { ok: true, json: async () => ({ ok: true, modell: 'testmodell',
            anweisung: 'x', ergebnisse: [{ schluessel: 'anweisung:style.md', ok: true,
                geaendert: false, alt: 'a\n', neu: 'a\n',
                begruendung: 'Drei Merksaetze nennen Jira.',
                funde: [{ art: 'treffer', text: 'jira_zugang' }],
                bytes_alt: 2, bytes_neu: 2 }] }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
};
// ⚠ WAEHREND DES LAUFS MUESSEN BEIDE KNOEPFE GESPERRT SEIN - sonst startet
// ein zweiter Lauf in den ersten hinein und ueberschreibt die Vorschlagsliste.
// Gemessen wird das IM Lauf (in der fetch-Attrappe), nicht davor oder danach.
let gesperrtImLauf = null;
const f10 = async (url, opt) => {
    if (/\/analyse$/.test(url) && gesperrtImLauf === null) {
        const a = document.getElementById('kb-cl-start');
        const b = document.getElementById('kb-cl-anw-start');
        gesperrtImLauf = !!(a && a.disabled) && !!(b && b.disabled);
    }
    return f10roh(url, opt);
};
window.fetch = f10; global.fetch = f10;
feld.value = 'Entferne alle Merksaetze zu Jira.';
feld.dispatchEvent(new window.Event('input'));
await M.cleanupMitAnweisung();
check('⚠ waehrend des Laufs sind BEIDE Knoepfe gesperrt', gesperrtImLauf === true);
const anfr = gesendet10.filter(g => /\/analyse$/.test(g.url));
check('der Klick loest einen Analyse-Lauf aus', anfr.length > 0);
check('⚠ die Anweisung geht mit',
      anfr.length > 0 && anfr[0].body.anweisung === 'Entferne alle Merksaetze zu Jira.');
check('und genau die markierten Dateien',
      anfr.length > 0 && Array.isArray(anfr[0].body.dateien) && anfr[0].body.dateien.length === 2);

// Gegenrichtung: der gewoehnliche Knopf schickt KEINE Anweisung - auch dann
// nicht, wenn im Feld etwas steht. Sonst taete er je nach Feldinhalt etwas
// anderes, ohne dass es an ihm steht.
gesendet10.length = 0;
M._cleanupDateien = [{ schluessel: 'anweisung:style.md', art: 'anweisung',
                       name: 'style.md', bytes: 900, herkunft: 'geaendert', zu_gross: false }];
M._cleanupListe();
const feld2 = document.getElementById('kb-cl-anw-text');
feld2.value = 'Das hier soll NICHT gelten.';
feld2.dispatchEvent(new window.Event('input'));
await M.cleanupAnalysieren();
const anfr2 = gesendet10.filter(g => /\/analyse$/.test(g.url));
check('⚠ "Analysieren" schickt keine Anweisung mit, obwohl das Feld gefuellt ist',
      anfr2.length > 0 && !anfr2[0].body.anweisung);

console.log('\n\x1b[1m10b. Das Ergebnis sagt, wozu es gehoert\x1b[0m');
M._cleanupVorschlaege = [{ schluessel: 'anweisung:style.md', ok: true, geaendert: false,
                           alt: 'a\n', neu: 'a\n',
                           begruendung: 'Drei Merksaetze nennen Jira.',
                           funde: [{ art: 'treffer', text: 'jira_zugang' }],
                           bytes_alt: 2, bytes_neu: 2 }];
M._cleanupVergleich('testmodell', '<b>Entferne</b> alles zu Jira');
const txt10 = bodyEl.textContent;
const echoEl = bodyEl.querySelector('.kb-cl-anw-echo');
// ⚠ GEMESSEN WIRD DER KASTEN, NICHT NUR DER TEXT. Steht die Anweisung
// irgendwo im Fliesstext, greift keine der Regeln, die sie vom Ergebnis
// absetzen - und sie liest sich wie ein Teil des Vorschlags.
check('⚠ die Anweisung steht ueber dem Ergebnis - in ihrem eigenen Kasten',
      !!echoEl && echoEl.textContent.includes('Entferne')
      && echoEl.textContent.includes('alles zu Jira'));
check('und der Kasten steht VOR der ersten Karte',
      !!echoEl && !!bodyEl.querySelector('.kb-cl-karte')
      && (echoEl.compareDocumentPosition(bodyEl.querySelector('.kb-cl-karte'))
          & window.Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
check('⚠ sie wird MASKIERT (sie kaeme sonst als Markup ins Admin-DOM)',
      !bodyEl.querySelector('.kb-cl-anw-echo b')
      && bodyEl.innerHTML.includes('&lt;b&gt;'));
check('⚠ bei "nichts geaendert" steht die ANTWORT da (sonst ist der Lauf wertlos)',
      txt10.includes('Drei Merksaetze nennen Jira.'));
check('auch die Funde werden gezeigt', txt10.includes('jira_zugang'));
check('es gibt einen Weg zurueck zur Auswahl',
      !!document.getElementById('kb-cl-zurueck'));

// Ohne Anweisung: kein Echo-Kasten, und der alte Hinweistext gilt.
M._cleanupVergleich('testmodell');
check('ohne Anweisung erscheint kein Echo-Kasten',
      !bodyEl.querySelector('.kb-cl-anw-echo'));

console.log('\n\x1b[1m10c. CSS und Texte\x1b[0m');
const CSS10 = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8')
                .replace(/\/\*[\s\S]*?\*\//g, '');
check('Positivkontrolle: der Kommentar-Filter hat gearbeitet',
      CSS10.includes('.kb-cl-anw') && !CSS10.includes('Eigene Anweisung: abgesetzter'));
const anwBlock = (CSS10.match(/\.kb-cl-anw-text\s*\{[^}]*\}/) || [''])[0];
check('das Feld hat eine eigene Regel', anwBlock.length > 10);
check('⚠ box-sizing: sonst laeuft es mit width:100% aus dem Kasten',
      /box-sizing\s*:\s*border-box/.test(anwBlock));
const echoBlock = (CSS10.match(/\.kb-cl-anw-echo\s*\{[^}]*\}/) || [''])[0];
check('⚠ min-width:0 am Echo - eine lange Anweisung sprengt sonst den Dialog',
      /min-width\s*:\s*0/.test(echoBlock));
['anw_titel', 'anw_hint', 'anw_ph', 'anw_btn', 'anw_btn_title', 'anw_btn_leer',
 'anw_note', 'anw_leer', 'anw_echo', 'result_hint_anw', 'back_title'].forEach(k => {
    const key = 'knowledge.cleanup.' + k;
    check(`Text "${k}" ist uebersetzt (kein Schluessel als Text)`,
          window.t(key) !== key && window.t(key).length > 2);
});
// ⚠ REGEL ueber BEIDE Sprachen: ein Schluessel, den nur DE kennt, faellt in der
// englischen Oberflaeche als Rohtext auf - und zwar erst beim Kunden.
const I18N10 = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');
['anw_titel', 'anw_btn', 'anw_echo', 'result_hint_anw', 'back_title'].forEach(k => {
    check(`"${k}" steht in DE UND EN`,
          (I18N10.match(new RegExp("'knowledge\\.cleanup\\." + k + "'", 'g')) || []).length === 2);
});

console.log('\n\x1b[1m10d. Vorlagen-Pulldown ueber dem Anweisungsfeld\x1b[0m');
// ⚠ AUSGEFUEHRT: ob eine Auswahl den Text WIRKLICH ins Feld setzt und dabei den
// Knopf freigibt, kann eine Quelltext-Suche nicht beantworten - genau daran
// haengt, ob der Klick danach ins Leere laeuft.
M._cleanupDateien = [{ schluessel: 'anweisung:style.md', art: 'anweisung',
                       name: 'style.md', bytes: 900, herkunft: 'geaendert', zu_gross: false }];
const f10d = async (url, opt) => {
    gesendet10.push({ url, body: JSON.parse((opt && opt.body) || '{}') });
    return { ok: true, json: async () => ({ ok: true, modell: 'testmodell', ergebnisse: [] }) };
};
window.fetch = f10d; global.fetch = f10d;
M._cleanupListe();
const vorl = document.getElementById('kb-cl-anw-vorlage');
const feld3 = document.getElementById('kb-cl-anw-text');
const knopf3 = document.getElementById('kb-cl-anw-start');
// Die ECHTE Liste aus dem Produktivcode - keine Zweitliste im Test.
const VORL = M._anwVorlagen();
// ⚠ NIE UNGEPRUEFT DEREFERENZIEREN (Register): fehlt das Pulldown, wirft der
// erste Zugriff darauf - der Lauf endet dann OHNE Bilanzzeile und ist von
// "nicht gelaufen" nicht zu unterscheiden. Ein Leer-Ersatz laesst jede
// folgende Pruefung ordentlich FAIL melden.
const LEER = { value: '', options: [], tagName: '', dispatchEvent() {},
               closest() { return null; },
               compareDocumentPosition() { return 0; } };
const vs = vorl || LEER;
check('das Pulldown wird gezeichnet', !!vorl && vorl.tagName === 'SELECT');
check('es steht VOR dem Eingabefeld (erst waehlen, dann bearbeiten)',
      !!vorl && !!feld3 && (vs.compareDocumentPosition(feld3)
          & window.Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
check('es liegt IM Anweisungs-Kasten, nicht in der Aktionszeile darueber',
      !!vorl && !!vs.closest('.kb-cl-anw'));
check('erster Eintrag ist "eigene Anweisung" und hat den leeren Wert',
      !!vorl && vs.options.length > 1 && vs.options[0].value === '');
check('jede Vorlage des Produktivcodes steht als Eintrag drin',
      !!vorl && VORL.every(k => [...vs.options].some(o => o.value === k)));
check('und keine darueber hinaus (die Liste ist die eine Quelle)',
      !!vorl && vs.options.length === VORL.length + 1);
check('⚠ die verlangte Sicherheits-Vorlage ist dabei', VORL.includes('sicherheit'));
check('die Eintraege tragen eine LESBARE Beschriftung, nicht den Auftragstext',
      !!vorl && [...vs.options].slice(1).every(o =>
          o.textContent.trim().length > 4 && o.textContent.trim().length < 60));
check('das Feld startet leer und der Knopf gesperrt',
      feld3.value === '' && knopf3.disabled === true);

// Auswahl -> Text im Feld, Knopf frei.
let gefragt = 0;
window.confirm = () => { gefragt++; return true; };
global.confirm = window.confirm;
vs.value = 'sicherheit';
vs.dispatchEvent(new window.Event('change'));
const txtSich = window.t('knowledge.cleanup.anw_vt_sicherheit');
check('⚠ die Wahl setzt den Auftragstext ins Feld', feld3.value === txtSich);
check('⚠ und der Knopf wird dabei frei (das input-Ereignis ist Pflicht)',
      knopf3.disabled === false);
check('bei leerem Feld wird NICHT nachgefragt', gefragt === 0);
check('das Pulldown nennt danach weiter die Vorlage', vs.value === 'sicherheit');
// ⚠ Der Anwender soll den ANFANG des Auftrags sehen, nicht dessen Schluss -
// `focus()` setzt den Cursor sonst hinter den Text und scrollt dorthin.
// Im Screenshot gesehen, waehrend die Messung gruen war.
check('⚠ der Cursor steht am Anfang (sonst liest man das Ende des Auftrags)',
      feld3.selectionStart === 0 && feld3.selectionEnd === 0 && feld3.scrollTop === 0);

// Vorlage -> andere Vorlage: nichts zu verlieren, also keine Rueckfrage.
vs.value = 'straffen';
vs.dispatchEvent(new window.Event('change'));
check('ein Wechsel zwischen zwei Vorlagen fragt nicht nach', gefragt === 0);
check('und setzt den neuen Text',
      feld3.value === window.t('knowledge.cleanup.anw_vt_straffen'));

// ⚠ Bearbeiten des eingesetzten Textes: das Pulldown darf danach nicht mehr
// behaupten, im Feld stehe die Vorlage.
feld3.value = window.t('knowledge.cleanup.anw_vt_straffen') + ' Aber nur Abschnitt 3.';
feld3.dispatchEvent(new window.Event('input'));
check('⚠ bearbeiteter Text stellt das Pulldown auf "eigene Anweisung" zurueck',
      vs.value === '');
check('der Text bleibt dabei unangetastet', /Abschnitt 3/.test(feld3.value));

// Getippter Text + abgelehnte Rueckfrage: nichts geht verloren.
window.confirm = () => { gefragt++; return false; };
global.confirm = window.confirm;
feld3.value = 'Meine eigene, muehsam getippte Anweisung.';
feld3.dispatchEvent(new window.Event('input'));
vs.value = 'veraltet';
vs.dispatchEvent(new window.Event('change'));
check('⚠ vor dem Ueberschreiben getippten Textes wird gefragt', gefragt === 1);
check('⚠ bei "nein" bleibt der getippte Text stehen',
      feld3.value === 'Meine eigene, muehsam getippte Anweisung.');
check('und das Pulldown faellt zurueck - die Wahl hat nicht stattgefunden',
      vs.value === '');
// Dieselbe Lage, diesmal bestaetigt.
window.confirm = () => { gefragt++; return true; };
global.confirm = window.confirm;
vs.value = 'veraltet';
vs.dispatchEvent(new window.Event('change'));
check('bei "ja" wird ersetzt',
      gefragt === 2 && feld3.value === window.t('knowledge.cleanup.anw_vt_veraltet'));

// Was am Ende wirklich rausgeht.
gesendet10.length = 0;
vs.value = 'sicherheit';
vs.dispatchEvent(new window.Event('change'));
await M.cleanupMitAnweisung();
const anfr3 = gesendet10.filter(g => /\/analyse$/.test(g.url));
check('⚠ der Vorlagentext geht als Anweisung raus',
      anfr3.length > 0 && anfr3[0].body.anweisung === txtSich);
// Und nach eigener Bearbeitung genau der BEARBEITETE Text - nicht die Vorlage.
gesendet10.length = 0;
feld3.value = 'Nur Kennwoerter, sonst nichts.';
feld3.dispatchEvent(new window.Event('input'));
await M.cleanupMitAnweisung();
const anfr4 = gesendet10.filter(g => /\/analyse$/.test(g.url));
check('⚠ ausgefuehrt wird immer der Feldinhalt, nicht die gewaehlte Vorlage',
      anfr4.length > 0 && anfr4[0].body.anweisung === 'Nur Kennwoerter, sonst nichts.');
window.confirm = () => true; global.confirm = () => true;

// ⚠ REGEL ueber die ECHTE Liste, keine Testliste: jede Vorlage braucht beide
// Schluessel in BEIDEN Sprachen. Eine fuenfte faellt damit von selbst auf.
const I10d = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');
VORL.forEach(k => {
    ['anw_v_' + k, 'anw_vt_' + k].forEach(s => {
        const key = 'knowledge.cleanup.' + s;
        check(`"${s}" ist uebersetzt und steht in DE UND EN`,
              window.t(key) !== key
              && (I10d.match(new RegExp("'knowledge\\.cleanup\\." + s + "'", 'g')) || []).length === 2);
    });
    const t = window.t('knowledge.cleanup.anw_vt_' + k);
    // Ein Auftrag von drei Woertern taugt nicht, und ueber MAX_ANWEISUNG (2000
    // Zeichen im Backend) wuerde er mit 400 abgewiesen - dann ist die Vorlage
    // ein Knopf, der nur eine Fehlermeldung erzeugt.
    check(`der Auftragstext "${k}" ist brauchbar lang und unter dem Deckel`,
          t.length > 80 && t.length < 2000);
});
['anw_vorl_label', 'anw_vorl_leer', 'anw_vorl_title', 'anw_vorl_ersetzen'].forEach(k => {
    const key = 'knowledge.cleanup.' + k;
    check(`Text "${k}" steht in DE UND EN`,
          window.t(key) !== key
          && (I10d.match(new RegExp("'knowledge\\.cleanup\\." + k + "'", 'g')) || []).length === 2);
});
const CSS10d = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8')
                 .replace(/\/\*[\s\S]*?\*\//g, '');
check('Positivkontrolle: der Kommentar-Filter hat gearbeitet',
      CSS10d.includes('.kb-cl-anw-vorl') && !CSS10d.includes('Vorlagen-Pulldown ueber dem Feld'));
const vBlock = (CSS10d.match(/\.kb-cl-anw-vorl\s*\{[^}]*\}/) || [''])[0];
check('das Pulldown hat eine eigene Regel', vBlock.length > 10);
check('⚠ min-width:0 - sonst sprengt der laengste Eintrag die Zeile',
      /min-width\s*:\s*0/.test(vBlock));
const zBlock = (CSS10d.match(/\.kb-cl-anw-vorl-zeile\s*\{[^}]*\}/) || [''])[0];
check('die Zeile bricht um, statt das Menue zu quetschen',
      /flex-wrap\s*:\s*wrap/.test(zBlock));

clearTimeout(wachhund);
console.log(`\n\x1b[1mErgebnis: ${OK} OK, ${FAIL} FAIL\x1b[0m`);
process.exit(FAIL ? 1 : 0);
})().catch(e => { console.log('\x1b[31mABBRUCH: ' + e.message + '\x1b[0m'); process.exit(1); });
