#!/usr/bin/env node
/*
 * Seite maximieren – EIN Knopf ⛶ oben rechts ueber den Kacheln (seite_breit.js).
 *
 * Vorgabe 2026-09-28: nach dem Vorbild von /wissen wandert der Maximieren-
 * Knopf aus den Karten (/feedback "Formular ausfuellen", /tracks "Ablagen" und
 * "Letzte Laeufe") nach AUSSERHALB der Container; danach dasselbe Schema fuer
 * die uebrigen Portal-Kacheln.
 *
 * Geprueft je Seite (jsdom, OHNE Layout):
 *   1. die Seite bindet seite_breit.js ein (nach i18n.js, falls vorhanden)
 *   2. genau EIN #jv-max, eindeutiger data-seite-Name
 *   3. der Knopf steht NICHT in einer Karte, nicht in der Titelleiste und
 *      nicht in einem Element, das per innerHTML neu geschrieben wird
 *      (/api: #ad-wrap), und VOR der ersten Karte
 *   4. genau EIN [data-jv-breit], und der Knopf steht davor oder darin
 *   5. Klick schaltet body.jv-breit, Zeichen, aria-pressed, Beschriftung,
 *      i18n-Attribute; zweiter Klick zurueck; Sprachwechsel zieht nach
 *   6. Zustand wird JE SEITE gemerkt; gesperrter Speicher ist kein Fehler
 *
 * Die BREITE selbst (theme.css) rechnet jsdom nicht – es ignoriert sogar die
 * Spezifitaet (gemessen: `body.x [data-y]` verliert gegen ein spaeteres
 * `.w`). Die misst `live_seite_breit_ui.py` im echten Chrome.
 *
 * Aufruf: node tests/test_seite_breit_ui.js   (JSDOM_PATH setzt den jsdom-Ort)
 * Exit 0 = gruen, 1 = Fehler, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = r => fs.readFileSync(path.join(ROOT, r), 'utf8');
const SEITE_BREIT = lies('frontend/js/seite_breit.js');
const I18N = lies('frontend/js/i18n.js');

// Die Portal-Kacheln mit gedeckeltem Inhaltsbereich. /chat und /userchat
// sind randlose Chat-Oberflaechen ohne Deckelung. /wissen war das Vorbild und
// nutzt seit 2026-09-28 denselben Baustein.
const SEITEN = ['wissen', 'feedback', 'tracks', 'support', 'sap', 'vemas', 'email', 'excel',
                'jira_addon', 'confluence_addon', 'ai_mouse', 'claude', 'supportagent', 'api'];

let ok = 0, fail = 0;
function c(name, bed, info) {
    if (bed) { ok++; console.log('  ✓ ' + name); }
    else { fail++; console.log('  ✗ ' + name + (info ? '  [' + info + ']' : '')); }
}

async function baue(datei, speicher) {
    const html = lies('frontend/' + datei + '.html');
    // Eingebundene Stylesheets inline einsetzen – jsdom laedt keine <link>s,
    // und die Deckelung von `.ja-main` steht in jira_addon.css.
    const mitCss = html.replace(/<link rel="stylesheet" href="\/static\/css\/([\w.-]+\.css)\?v=\d+">/g,
        (m, f) => '<style>' + lies('frontend/css/' + f) + '</style>');
    const d = new JSDOM(mitCss, { url: 'https://x/' + datei, runScripts: 'outside-only' });
    const w = d.window;
    if (speicher === 'gesperrt') {
        Object.defineProperty(w, 'localStorage', { configurable: true,
            get() { throw new Error('SecurityError'); } });
    } else if (speicher) {
        for (const k of Object.keys(speicher)) w.localStorage.setItem(k, speicher[k]);
    }
    // i18n.js liest `jarvis_lang` OHNE try (Bestand) – bei gesperrtem Speicher
    // wuerfe schon das; hier geht es nur um seite_breit.js.
    if (/\/static\/js\/i18n\.js\?v=/.test(html) && speicher !== 'gesperrt') w.eval(I18N);
    w.eval(SEITE_BREIT);
    // seite_breit.js bindet erst bei DOMContentLoaded, und das feuert in jsdom
    // NACH dem Konstruktor – ein Klick davor traefe einen ungebundenen Knopf.
    if (w.document.readyState === 'loading') {
        await new Promise(r => w.document.addEventListener('DOMContentLoaded', r));
    }
    return { w, d: w.document, html };
}

const KARTE = '[class$="-card"], [class*="-card "], .ja-card, .st-card, .wi-section, section';

(async () => {
    // ── Positivkontrolle: ohne sie waeren alle Pruefungen unten trivial ──────
    console.log('\n0. Grundlage');
    const fehlt = SEITEN.filter(s => !fs.existsSync(path.join(ROOT, 'frontend', s + '.html')));
    c(SEITEN.length + ' Seiten vorhanden', fehlt.length === 0, fehlt.join(','));
    c('seite_breit.js schaltet body.jv-breit', /classList\.toggle\('jv-breit'/.test(SEITE_BREIT));
    if (fehlt.length) { console.log('ABBRUCH: Seiten fehlen'); process.exit(2); }

    const namen = {};
    for (const s of SEITEN) {
        console.log('\n── /' + s);
        const { w, d, html } = await baue(s);

        // 1. Einbindung
        const iSB = html.search(/<script src="\/static\/js\/seite_breit\.js\?v=\d+"><\/script>/);
        const iI18n = html.search(/<script src="\/static\/js\/i18n\.js\?v=\d+"><\/script>/);
        c('bindet seite_breit.js ein', iSB >= 0);
        if (iI18n >= 0) c('… NACH i18n.js (sonst fehlen die Beschriftungen beim Start)', iSB > iI18n);

        // 2. genau ein Knopf
        const alle = d.querySelectorAll('#jv-max, .jv-max-btn');
        const b = d.getElementById('jv-max');
        c('genau EIN Maximieren-Knopf', alle.length === 1 && !!b, alle.length + 'x');
        if (!b) continue;
        const name = b.getAttribute('data-seite') || '';
        c('eindeutiger data-seite-Name', !!name && !namen[name], name + ' auch in ' + namen[name]);
        namen[name] = s;
        c('startet als "Maximieren" (⛶, aria-pressed=false)',
          b.textContent.trim() === '⛶' && b.getAttribute('aria-pressed') === 'false'
          && b.getAttribute('data-i18n-title') === 'common.maximize'
          && b.getAttribute('data-i18n-aria') === 'common.maximize');

        // 3. Lage
        c('NICHT in einer Karte', !b.closest(KARTE), (b.closest(KARTE) || {}).className);
        c('NICHT in der Titelleiste', !b.closest('header, .topbar, .wi-topbar, .sa-topbar, .ad-top'));
        c('NICHT im per innerHTML neu geschriebenen Listenbereich (/api)', !b.closest('#ad-wrap'));
        const karte = d.querySelector('[data-jv-breit] ' + KARTE.split(', ').join(', [data-jv-breit] '));
        if (karte) {
            c('steht VOR der ersten Kachel (ganz oben)',
              (b.compareDocumentPosition(karte) & w.Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
        }

        // 4. der Bereich, der breit wird
        const bereich = d.querySelectorAll('[data-jv-breit]');
        c('genau EIN Bereich [data-jv-breit]', bereich.length === 1, bereich.length + 'x');
        if (bereich.length === 1) {
            const vor = (b.compareDocumentPosition(bereich[0]) & w.Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
            c('der Knopf steht davor oder als erstes darin',
              vor || bereich[0].firstElementChild === b.parentElement);
            // Positivkontrolle fuer live_seite_breit_ui.py: der Bereich IST gedeckelt.
            const mw = w.getComputedStyle(bereich[0]).maxWidth;
            c('Positivkontrolle: der Bereich ist ohne Maximieren gedeckelt (px)', /px$/.test(mw), mw);
        }

        // 5. Klick
        b.click();
        c('Klick: body.jv-breit', d.body.classList.contains('jv-breit'));
        c('… 🗗, aria-pressed=true, .active',
          b.textContent === '\u{1F5D7}' && b.getAttribute('aria-pressed') === 'true'
          && b.classList.contains('active'), JSON.stringify(b.textContent));
        c('… Titel und aria-label "Verkleinern"',
          b.title === 'Verkleinern' && b.getAttribute('aria-label') === 'Verkleinern', b.title);
        c('… die i18n-Attribute wandern mit',
          b.getAttribute('data-i18n-title') === 'common.minimize'
          && b.getAttribute('data-i18n-aria') === 'common.minimize');
        if (w.setLang) {
            w.setLang('en');
            c('… Sprachwechsel: "Restore"', b.title === 'Restore'
              && b.getAttribute('aria-label') === 'Restore', b.title);
            w.setLang('de');
        }
        // `data-speicher` nur fuer einen BESTEHENDEN Schluessel (/wissen).
        const LS = b.getAttribute('data-speicher') || ('jarvis_breit_' + name);
        c('gemerkt: ' + LS + ' = 1', w.localStorage.getItem(LS) === '1');
        b.click();
        c('zweiter Klick verkleinert wieder',
          !d.body.classList.contains('jv-breit') && b.textContent === '⛶'
          && b.title === 'Maximieren' && b.getAttribute('aria-pressed') === 'false');
        c('… und merkt 0', w.localStorage.getItem(LS) === '0');
        w.close();

        // 6. gemerkter Zustand
        const g = await baue(s, { [LS]: '1' });
        c('frisch geladen mit gemerktem "1": startet breit',
          g.d.body.classList.contains('jv-breit')
          && g.d.getElementById('jv-max').getAttribute('aria-pressed') === 'true');
        g.w.close();
        const f = await baue(s, { ['jarvis_breit_andere']: '1' });
        c('… der Zustand einer ANDEREN Seite wirkt hier nicht',
          !f.d.body.classList.contains('jv-breit'));
        f.w.close();
        let wurf = null, gs = null;
        try { gs = await baue(s, 'gesperrt'); gs.d.getElementById('jv-max').click(); }
        catch (e) { wurf = e; }
        c('gesperrter Speicher: kein Fehler, Knopf wirkt trotzdem',
          !wurf && gs && gs.d.body.classList.contains('jv-breit'), wurf && wurf.message);
        if (gs) gs.w.close();
    }

    // ── Kein Rest der alten Bauform (Vollbild EINER Karte) ───────────────────
    console.log('\n── Altbestand');
    const TR = lies('frontend/tracks.html') + lies('frontend/js/tracks.js');
    const WIQ = lies('frontend/wissen.html') + lies('frontend/js/wissen.js');
    c('/wissen: keine eigene Fassung mehr (eine zweite liefe auseinander)',
      !/wi-max|wi-breit|maxSetzen|maxInit|_MAX_LS/.test(WIQ));
    c('/wissen: gemerkter Zustand bleibt unter dem alten Schluessel',
      /data-speicher="jarvis_wissen_breit"/.test(lies('frontend/wissen.html')));
    const FB = lies('frontend/feedback.html') + lies('frontend/js/feedback.js') + lies('frontend/css/feedback.css');
    c('/tracks: kein Einzel-Vollbild mehr', !/is-max|st-maxed|data-act="max"|maxUmschalten/.test(TR));
    c('/feedback: kein Einzel-Vollbild mehr', !/is-max|fb-maxed|data-act="max"|maxUmschalten/.test(FB));
    c('i18n: die alten Bereichs-Schluessel sind weg',
      !/'(feedback|tracks|wissen)\.m(ax|in)imize'/.test(I18N));
    for (const k of ['common.maximize', 'common.minimize']) {
        const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length;
        c('„' + k + '" in DE und EN', n === 2, n + 'x');
    }
    // Dieselben Zeichen wie der Vollbild-Knopf des Einstellungs-Dialogs.
    const SETQ = lies('frontend/settings.html');
    c('dieselben Zeichen wie der Einstellungs-Dialog (⛶ / 🗗)',
      /id="btn-maximize-settings"[^>]*>\u26f6</.test(SETQ)
      && /an \? '&#128471;' : '&#9974;'/.test(SEITE_BREIT));

    console.log('\n' + '='.repeat(70));
    console.log(ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => {
    console.log('\nABBRUCH: ' + (e && e.stack || e));
    console.log(ok + ' OK, ' + (fail + 1) + ' FAIL (ABGEBROCHEN)');
    process.exit(1);
});
