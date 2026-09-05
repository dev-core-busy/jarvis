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
               '_cleanupListe'].map(methode);
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

clearTimeout(wachhund);
console.log(`\n\x1b[1mErgebnis: ${OK} OK, ${FAIL} FAIL\x1b[0m`);
process.exit(FAIL ? 1 : 0);
})().catch(e => { console.log('\x1b[31mABBRUCH: ' + e.message + '\x1b[0m'); process.exit(1); });
