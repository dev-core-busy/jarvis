#!/usr/bin/env node
/**
 * Waechter: Sammel-Kaestchen je Bereich im Dialog "Prompt optimieren".
 *
 * ⚠ GEMELDET (2026-09-07): "Bereiche mit 'alle markieren/entfernen' ausstatten,
 * da ansonsten zuviel geklickt werden muss." GEMESSEN auf DEV: 15 Eintraege in
 * DREI Bereichen (anweisung 2, gedaechtnis 7, lernnotiz 6) - wer nur die
 * Anweisungen pruefen will, klickt 13 Haekchen weg.
 *
 * ⚠ DER ECHTE RENDERER LAEUFT gegen die ECHTE settings.html. Ein Test, der
 * sein Markup selbst schreibt, prueft seine eigene Annahme (Register) - genau
 * daran war test_aufraeumen_ui.js schon einmal blind.
 *
 * Die Falle, gegen die hier gemessen wird: das Kaestchen sitzt in einem
 * <label>. Der Browser schaltet es dabei SELBST um; ein zusaetzliches
 * cb.checked = !cb.checked hebt sich auf und der Klick tut unterm Strich gar
 * nichts (im Projekt beim AD-Picker bezahlt). jsdom setzt die
 * Label-Aktivierungsweitergabe um - deshalb wird wirklich geklickt.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const REPO = path.dirname(__dirname);
let OK = 0, FAIL = 0;
function check(name, bed) {
    if (typeof bed !== 'boolean') {
        console.log(`\x1b[31mABBRUCH\x1b[0m: check('${name}') bekam ${typeof bed}`);
        process.exit(2);
    }
    console.log((bed ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name);
    bed ? OK++ : FAIL++;
}

// ── Wachhund: ein haengender Lauf darf nicht wie ein bestandener aussehen ──
const hund = setTimeout(() => {
    console.log('  \x1b[31m✗\x1b[0m ABBRUCH: Zeitlimit');
    console.log(`\n\x1b[1m${OK} OK, ${FAIL + 1} FAIL\x1b[0m`);
    process.exit(1);
}, 40000);
let bilanz = false;
process.on('exit', (c) => { if (!bilanz && c === 0) { console.log('\x1b[31mOHNE BILANZ\x1b[0m'); process.exitCode = 1; } });

const html = fs.readFileSync(path.join(REPO, 'frontend/settings.html'), 'utf8');
const dom = new JSDOM(html, { url: 'https://localhost/settings', runScripts: 'outside-only' });
const { window } = dom;
window.localStorage.setItem('jarvis_token', 'x');
window.fetch = () => Promise.resolve({ ok: true, json: async () => ({}), text: async () => '' });
global.fetch = window.fetch;

// ECHTE i18n und der ECHTE Renderer - kein Nachbau.
window.eval(fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8'));
window.eval(fs.readFileSync(path.join(REPO, 'frontend/js/icons.js'), 'utf8'));
window.eval(fs.readFileSync(path.join(REPO, 'frontend/js/knowledge.js'), 'utf8'));

const km = window.knowledgeManager;
const doc = window.document;

// ── Der ECHTE DEV-Bestand als Datensatz ──────────────────────────────────
const D = [];
const bauen = (art, n, gross) => {
    for (let i = 0; i < n; i++) D.push({
        art, schluessel: `${art}-${i}`, name: `${art}_${i}.md`,
        bytes: 2048, herkunft: 'geaendert', zu_gross: !!gross && i === 0,
    });
};
bauen('anweisung', 2);
bauen('gedaechtnis', 7);
bauen('lernnotiz', 6, true);   // einer davon GESPERRT (zu gross)
km._cleanupDateien = D;

if (typeof km._cleanupListe !== 'function' || typeof km._cleanupAuswahlVerdrahten !== 'function') {
    check('knowledge.js kennt _cleanupListe und _cleanupAuswahlVerdrahten', false);
    bilanz = true; clearTimeout(hund);
    console.log(`\n\x1b[1m${OK} OK, ${FAIL} FAIL\x1b[0m`);
    process.exit(1);
}
km._cleanupListe();

const box = doc.getElementById('kb-cleanup-body');
// ⚠ NIE UNGEPRUEFT DEREFERENZIEREN: fehlt das Kaestchen (Gegenprobe), wirft
// jedes `.closest`/`.click()` darauf - der Lauf braeche OHNE Bilanzzeile ab
// und waere von "nicht gelaufen" nicht zu unterscheiden (Register).
const LEER = { checked: false, indeterminate: false, disabled: true, title: '',
               click() {}, closest() { return null; } };
const master = (art) => box.querySelector(`.kb-cl-alle[data-art="${art}"]`) || LEER;
const zahl = (art) => box.querySelector(`.kb-cl-gruppe-zahl[data-art="${art}"]`)
                      || { textContent: '' };
const boxen = (art) => [...box.querySelectorAll(`.kb-cl-gruppe[data-art="${art}"] .kb-cl-sel`)];
const gewaehlt = (art) => boxen(art).filter(c => c.checked).length;

console.log('\x1b[1m1. Es gibt je Bereich ein Sammel-Kaestchen\x1b[0m');
check('⚠ es ist ueberhaupt eines im Markup (sonst ist alles Weitere sinnlos)',
      box.querySelectorAll('.kb-cl-alle').length > 0);
check('drei Bereiche gerendert',
      box.querySelectorAll('.kb-cl-gruppe').length === 3);
check('jeder Bereich hat genau ein Sammel-Kaestchen',
      ['anweisung', 'gedaechtnis', 'lernnotiz'].every(a =>
          box.querySelectorAll(`.kb-cl-alle[data-art="${a}"]`).length === 1));
check('es sitzt IM Titel (ein Klick auf den Bereichsnamen wirkt)',
      !!master('anweisung').closest('.kb-cl-gruppe-titel'));
check('der Titel ist ein <label> (sonst schaltet der Klick auf den Text nicht)',
      master('anweisung').closest('label') !== null);

console.log('\n\x1b[1m2. Der gemeldete Fall: EIN Klick statt 13\x1b[0m');
check('Ausgangslage: alles gewaehlt', gewaehlt('gedaechtnis') === 7);
master('gedaechtnis').click();                       // -> abwaehlen
check('⚠ ein Klick entfernt ALLE Haken des Bereichs', gewaehlt('gedaechtnis') === 0);
check('die anderen Bereiche bleiben unangetastet',
      gewaehlt('anweisung') === 2 && gewaehlt('lernnotiz') === 5);
master('gedaechtnis').click();                       // -> wieder alle
check('⚠ ein zweiter Klick markiert wieder alle', gewaehlt('gedaechtnis') === 7);
check('kein Doppel-Toggle im <label> (der Klick wirkt genau einmal)',
      master('gedaechtnis').checked === true);

console.log('\n\x1b[1m3. Gesperrte Eintraege bleiben unangetastet\x1b[0m');
const gesperrt = boxen('lernnotiz').filter(c => c.disabled);
check('der Datensatz hat einen gesperrten Eintrag', gesperrt.length === 1);
check('er ist nicht gewaehlt', gesperrt[0].checked === false);
master('lernnotiz').click();
master('lernnotiz').click();
check('⚠ er bleibt auch nach alle/keine ungewaehlt', gesperrt[0].checked === false);
check('die Zahl zaehlt nur die WAEHLBAREN (5, nicht 6)',
      zahl('lernnotiz').textContent === '(5/5)');

console.log('\n\x1b[1m4. Der Zustand ist ABLESBAR, nicht nur sichtbar\x1b[0m');
boxen('anweisung')[0].click();                       // eine abwaehlen
check('die Zahl folgt der Einzelauswahl', zahl('anweisung').textContent === '(1/2)');
check('⚠ Teilauswahl steht als indeterminate da (sonst sieht sie aus wie "keine")',
      master('anweisung').indeterminate === true);
check('und das Sammel-Kaestchen ist dabei NICHT gesetzt',
      master('anweisung').checked === false);
master('anweisung').click();
check('aus der Teilauswahl heraus waehlt ein Klick ALLES',
      gewaehlt('anweisung') === 2 && master('anweisung').indeterminate === false);

console.log('\n\x1b[1m5. Beschriftung und Sprache\x1b[0m');
check('der Titel nennt den Bereich im Klartext',
      /Anweisungen/.test(box.querySelector('.kb-cl-gruppe[data-art="anweisung"] .kb-cl-gruppe-titel').textContent));
check('das Kaestchen traegt eine Beschriftung', !!master('anweisung').title);
check('sie wechselt mit dem Zustand',
      (() => { const a = master('anweisung').title; master('anweisung').click();
               const b = master('anweisung').title; master('anweisung').click(); return a !== b; })());
const i18n = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');
check('beide Schluessel gibt es in DE UND EN',
      (i18n.match(/'knowledge\.cleanup\.all_title'/g) || []).length === 2 &&
      (i18n.match(/'knowledge\.cleanup\.none_title'/g) || []).length === 2);

console.log('\n\x1b[1m6. Die Auswahl wird auch WIRKLICH abgeschickt\x1b[0m');
// ⚠ Ohne diese Pruefung koennte das Kaestchen huebsch aussehen und trotzdem
// nichts bewirken: cleanupAnalysieren liest `.kb-cl-sel:checked`.
master('gedaechtnis').click();                        // gedaechtnis abwaehlen
const gesendet = [...doc.querySelectorAll('.kb-cl-sel:checked')].map(c => c.value);
check('abgewaehlte Bereiche stehen nicht in der Auswahl',
      !gesendet.some(v => v.startsWith('gedaechtnis')));
check('die uebrigen schon',
      gesendet.some(v => v.startsWith('anweisung')) && gesendet.some(v => v.startsWith('lernnotiz')));
const q = fs.readFileSync(path.join(REPO, 'frontend/js/knowledge.js'), 'utf8');
check('cleanupAnalysieren liest genau diese Kaestchen',
      /cleanupAnalysieren[\s\S]{0,200}\.kb-cl-sel:checked/.test(q));

console.log('\n\x1b[1m7. CSS: der Titel bleibt klickbar und lesbar\x1b[0m');
const css = fs.readFileSync(path.join(REPO, 'frontend/css/style.css'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '');   // Kommentare raus (Register)
const regel = (css.match(/\.kb-cl-gruppe-titel\s*\{[^}]*\}/) || [''])[0];
check('Positivkontrolle: die Regel wurde gefunden', regel.length > 20);
check('sie ist ein Flex-Container mit Abstand',
      /display:\s*inline-flex/.test(regel) && /gap:/.test(regel));
check('⚠ inline-flex, damit nicht die halbe Zeile daneben klickbar ist',
      !/display:\s*flex\b/.test(regel));
check('der Zeiger zeigt, dass es klickbar ist', /cursor:\s*pointer/.test(regel));
check('Text wird beim Klicken nicht markiert', /user-select:\s*none/.test(regel));
check('die Zahl hat eine eigene, gedaempfte Regel',
      /\.kb-cl-gruppe-zahl\s*\{[^}]*--text-muted/.test(css));

bilanz = true;
clearTimeout(hund);
window.close();
console.log(`\n\x1b[1m${OK} OK, ${FAIL} FAIL\x1b[0m`);
process.exit(FAIL ? 1 : 0);
