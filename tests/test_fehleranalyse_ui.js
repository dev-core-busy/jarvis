#!/usr/bin/env node
/**
 * Waechter: Reiter "Fehleranalyse" (frontend/js/fehleranalyse.js).
 *
 * Gemessen gegen die ECHTE settings.html mit echtem i18n.js und echtem Modul;
 * fetch ist eine Attrappe, die ueber den PFAD routet (Register) und jeden
 * Aufruf aufzeichnet. Geprueft wird die WIRKUNG am DOM:
 *   - Benutzer -> Laeufe -> Knoepfe (gesperrt, bis ein Lauf gewaehlt ist)
 *   - "Analysieren" gesperrt, wenn das Admin-Profil kein Modell hat
 *   - Dossier-Knopf sendet Lauf + Beschreibung, Ergebnis per textContent
 *     (eine Markup-Nutzlast im Dossier erzeugt KEIN Element)
 *   - Analyse zeigt Text + Meta; scheitert sie, bleibt das Dossier stehen
 *   - Verdrahtung in app.js am Syntaxbaum (acorn)
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

let ok = 0, fail = 0;
function pruefe(text, bedingung, zusatz) {
    if (typeof text !== 'string' || typeof bedingung === 'string') {
        console.error('TESTFEHLER: pruefe(Text, Bedingung) vertauscht:', text);
        process.exit(2);
    }
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}
process.on('unhandledRejection', (e) => {
    fail++; console.log('  FAIL unbehandelte Zurueckweisung: ' + (e && e.message || e));
});
const warte = (ms) => new Promise(r => setTimeout(r, ms || 0));

const LAEUFE = [
    { id: '1792993217000-1', ts: 1792993217, task: 'liefere eine Befundliste als csv', steps: 4,
      duration_ms: 40000, error: null, model: 'm', client_type: 'browser', username: 'firma\\m.mustermann' },
    { id: '1792990000000-1', ts: 1792990000, task: 'zweiter Lauf', steps: 1,
      duration_ms: 2000, error: 'x', model: 'm', client_type: 'browser', username: 'firma\\m.mustermann' },
];
const NUTZLAST = '<img src=x onerror="window.__xss=1">';

async function aufbau(opts) {
    opts = opts || {};
    const dom = new JSDOM(lies('frontend/settings.html'), {
        url: 'https://localhost/settings', runScripts: 'outside-only', pretendToBeVisual: true,
    });
    const w = dom.window;
    w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {},
                                             addEventListener() {}, removeEventListener() {} }));
    w.authToken = 'tok';
    const aufrufe = [];
    const profil = opts.profil !== undefined ? opts.profil
        : { name: 'Admin-Profil', provider: 'openai_compatible', model: 'qwen' };
    w.fetch = async (url, init) => {
        const pfad = String(url).split('?')[0];
        aufrufe.push({ url: String(url), pfad, init: init || {} });
        const antwort = (status, daten) => ({ ok: status < 400, status, json: async () => daten });
        if (pfad === '/api/conv_log/users') return antwort(200, ['firma\\m.mustermann', 'firma\\e.beispiel']);
        if (pfad === '/api/fehleranalyse/laeufe') {
            const ben = new URL(String(url), 'https://localhost').searchParams.get('benutzer');
            return antwort(200, { ok: true, profil, laeufe: ben === 'firma\\m.mustermann' ? LAEUFE : [] });
        }
        if (pfad === '/api/fehleranalyse/dossier') {
            return antwort(200, { ok: true, dossier: '# Dossier\n' + NUTZLAST,
                                  kennzahlen: { journal: 7, sicherheit: 1, fundstellen: 2, abgeschnitten: 1 } });
        }
        if (pfad === '/api/fehleranalyse/analyse') {
            if (opts.analyseKaputt) {
                return antwort(200, { ok: true, dossier: '# Dossier B', kennzahlen: {},
                                      analyse_ok: false, analyse_fehler: 'Modell nicht erreichbar' });
            }
            return antwort(200, { ok: true, dossier: '# Dossier A', kennzahlen: {},
                                  analyse_ok: true, analyse: '### Ursache\n' + NUTZLAST,
                                  modell: 'qwen', profil: 'Admin-Profil', analyse_abgeschnitten: true });
        }
        return antwort(404, { error: 'unbekannt ' + pfad });
    };
    w.eval(lies('frontend/js/icons.js'));
    w.eval(lies('frontend/js/i18n.js'));
    w.eval(lies('frontend/js/fehleranalyse.js'));
    await warte(10);
    return { dom, w, d: w.document, aufrufe };
}

function waehle(w, sel, wert) {
    if (!Array.prototype.some.call(sel.options, o => o.value === wert)) {
        throw new Error('Option fehlt: ' + wert);      // sonst verpufft der Wert still (Register)
    }
    sel.value = wert;
    sel.dispatchEvent(new w.Event('change'));
}

(async () => {
    console.log('\n1. Aufbau und Laden');
    let { w, d, aufrufe } = await aufbau();
    pruefe('Positivkontrolle: Reiter und Modul vorhanden',
           !!d.getElementById('settings-tab-fehleranalyse') && !!w.Fehleranalyse);
    pruefe('Knopf in der Reiterleiste', !!d.querySelector('.settings-tab-btn[data-settings-tab="fehleranalyse"]'));
    await w.Fehleranalyse.onShow();
    await warte(10);
    const ben = d.getElementById('fa-benutzer'), lauf = d.getElementById('fa-lauf');
    const bD = d.getElementById('fa-dossier-btn'), bA = d.getElementById('fa-analyse-btn');
    pruefe('Benutzerliste gefuellt', ben.options.length === 3, ben.options.length);
    pruefe('ohne Benutzer: Lauf-Auswahl gesperrt', lauf.disabled === true);
    pruefe('ohne Lauf: beide Knoepfe gesperrt', bD.disabled && bA.disabled);
    pruefe('Profilhinweis nennt Profil, Anbieter und Modell',
           /Admin-Profil/.test(d.getElementById('fa-profil').textContent)
           && /openai_compatible/.test(d.getElementById('fa-profil').textContent)
           && /qwen/.test(d.getElementById('fa-profil').textContent),
           d.getElementById('fa-profil').textContent);

    console.log('\n2. Benutzer -> Laeufe -> Knoepfe');
    waehle(w, ben, 'firma\\m.mustermann');
    await warte(20);
    pruefe('Laeufe geladen (Platzhalter + 2)', lauf.options.length === 3, lauf.options.length);
    pruefe('der Benutzer geht kodiert in die Abfrage',
           aufrufe.some(a => a.pfad === '/api/fehleranalyse/laeufe'
                        && a.url.includes('benutzer=firma%5Cm.mustermann')));
    pruefe('ein Lauf mit Fehler ist im Text gekennzeichnet (nicht nur per Farbe)',
           /Fehler/.test(lauf.options[2].textContent), lauf.options[2].textContent);
    pruefe('noch kein Lauf gewaehlt: Knoepfe weiter gesperrt', bD.disabled && bA.disabled);
    waehle(w, lauf, '1792993217000-1');
    pruefe('⚠ mit Lauf: beide Knoepfe frei', !bD.disabled && !bA.disabled);
    waehle(w, ben, 'firma\\e.beispiel');
    await warte(20);
    pruefe('Benutzer ohne Laeufe: Auswahl gesperrt, Knoepfe gesperrt',
           lauf.disabled && bD.disabled && bA.disabled, lauf.options[0] && lauf.options[0].textContent);

    console.log('\n3. Dossier');
    waehle(w, ben, 'firma\\m.mustermann');
    await warte(20);
    waehle(w, lauf, '1792993217000-1');
    d.getElementById('fa-beschreibung').value = 'bekommt Zugriff verweigert';
    bD.click();
    await warte(20);
    const post = aufrufe.filter(a => a.pfad === '/api/fehleranalyse/dossier');
    let koerper = {};
    try { koerper = JSON.parse(post.length ? post[0].init.body : '{}'); } catch (e) { koerper = {}; }
    pruefe('⚠ POST mit Lauf und Beschreibung', post.length === 1 && post[0].init.method === 'POST'
           && koerper.id === '1792993217000-1' && koerper.beschreibung === 'bekommt Zugriff verweigert',
           JSON.stringify(koerper));
    const box = d.getElementById('fa-dossier-box');
    pruefe('Dossier-Box sichtbar', box.hidden === false);
    pruefe('⚠ Dossier als Text: die Nutzlast steht als Zeichen da',
           d.getElementById('fa-dossier').textContent.includes(NUTZLAST));
    pruefe('⚠ und erzeugt KEIN Element', d.querySelectorAll('#fa-dossier img').length === 0 && !w.__xss);
    pruefe('Kennzahlen stehen darin', /7 Journalzeilen/.test(d.getElementById('fa-kennzahlen').textContent)
           && /1 am Längenlimit/.test(d.getElementById('fa-kennzahlen').textContent),
           d.getElementById('fa-kennzahlen').textContent);
    pruefe('Analyse-Box bleibt beim reinen Dossier zu', d.getElementById('fa-analyse-box').hidden === true);
    pruefe('nach dem Lauf sind die Knoepfe wieder frei', !bD.disabled && !bA.disabled);

    console.log('\n4. Analyse');
    bA.click();
    await warte(20);
    const ana = aufrufe.filter(a => a.pfad === '/api/fehleranalyse/analyse');
    pruefe('POST an /analyse', ana.length === 1 && ana[0].init.method === 'POST');
    pruefe('Analyse-Box sichtbar mit Text', d.getElementById('fa-analyse-box').hidden === false
           && d.getElementById('fa-analyse').textContent.startsWith('### Ursache'));
    pruefe('⚠ Analyse als Text, kein Element', d.querySelectorAll('#fa-analyse img').length === 0);
    pruefe('Meta nennt Modell, Profil und den Abbruch',
           /qwen/.test(d.getElementById('fa-analyse-meta').textContent)
           && /Admin-Profil/.test(d.getElementById('fa-analyse-meta').textContent)
           && /abgeschnitten/.test(d.getElementById('fa-analyse-meta').textContent),
           d.getElementById('fa-analyse-meta').textContent);
    pruefe('das Dossier steht auch nach der Analyse', d.getElementById('fa-dossier').textContent === '# Dossier A');

    console.log('\n5. Analyse scheitert: Fehler sichtbar, Dossier bleibt');
    ({ w, d, aufrufe } = await aufbau({ analyseKaputt: true }));
    await w.Fehleranalyse.onShow(); await warte(10);
    waehle(w, d.getElementById('fa-benutzer'), 'firma\\m.mustermann'); await warte(20);
    waehle(w, d.getElementById('fa-lauf'), '1792993217000-1');
    d.getElementById('fa-analyse-btn').click(); await warte(20);
    const fe = d.getElementById('fa-fehler');
    pruefe('⚠ Fehlerzeile sichtbar mit Grund', fe.style.display === 'block' && /Modell nicht erreichbar/.test(fe.textContent),
           fe.textContent);
    pruefe('Analyse-Box zu', d.getElementById('fa-analyse-box').hidden === true);
    pruefe('⚠ Dossier trotzdem sichtbar', d.getElementById('fa-dossier-box').hidden === false
           && d.getElementById('fa-dossier').textContent === '# Dossier B');

    console.log('\n6. Ohne Profil-Modell kein Analysieren');
    ({ w, d } = await aufbau({ profil: { name: '', provider: '', model: '' } }));
    await w.Fehleranalyse.onShow(); await warte(10);
    waehle(w, d.getElementById('fa-benutzer'), 'firma\\m.mustermann'); await warte(20);
    waehle(w, d.getElementById('fa-lauf'), '1792993217000-1');
    pruefe('⚠ Analysieren gesperrt, Dossier frei',
           d.getElementById('fa-analyse-btn').disabled && !d.getElementById('fa-dossier-btn').disabled);
    pruefe('der Hinweis sagt warum', /kein Profil/.test(d.getElementById('fa-profil').textContent),
           d.getElementById('fa-profil').textContent);

    console.log('\n7. Verdrahtung in app.js (Syntaxbaum) und i18n');
    const acorn = require(path.join(ROOT, 'node_modules/acorn'));
    const app = lies('frontend/js/app.js');
    const baum = acorn.parse(app, { ecmaVersion: 'latest', sourceType: 'script', allowHashBang: true });
    let inListe = false, zweig = false;
    (function lauf(n) {
        if (!n || typeof n.type !== 'string') return;
        if (n.type === 'VariableDeclarator' && n.id && n.id.name === 'allSettingsTabs') {
            const t = app.slice(n.init.start, n.init.end);
            inListe = /\btabFehleranalyse\b/.test(t);
        }
        if (n.type === 'IfStatement' && n.test) {
            const bed = app.slice(n.test.start, n.test.end);
            if (/target === 'fehleranalyse'/.test(bed)) {
                zweig = /Fehleranalyse\.onShow\(\)/.test(app.slice(n.consequent.start, n.consequent.end));
            }
        }
        for (const k of Object.keys(n)) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach(lauf);
            else if (v && typeof v.type === 'string') lauf(v);
        }
    })(baum);
    pruefe('⚠ der Reiter steht in allSettingsTabs (sonst bleibt er beim Wechsel offen)', inListe);
    pruefe('⚠ der Zweig ruft Fehleranalyse.onShow()', zweig);
    const i18n = lies('frontend/js/i18n.js');
    const deStart = i18n.indexOf('    de: {'), enStart = i18n.indexOf('    en: {');
    pruefe('Positivkontrolle: beide Sprachbloecke gefunden', deStart > 0 && enStart > deStart);
    const keys = new Set();
    const html = lies('frontend/settings.html') + lies('frontend/js/fehleranalyse.js');
    (html.match(/\bfa\.[a-z_]+/g) || []).forEach(k => keys.add(k));
    keys.add('settings.tab.fehleranalyse');
    const de = i18n.slice(deStart, enStart), en = i18n.slice(enStart);
    const fehlt = [...keys].filter(k => !de.includes("'" + k + "'") || !en.includes("'" + k + "'"));
    pruefe('Positivkontrolle: Schluessel gefunden', keys.size >= 20, keys.size);
    pruefe('⚠ jeder fa.*-Schluessel steht in DE und EN', fehlt.length === 0, fehlt.join(', '));

    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
