#!/usr/bin/env node
/**
 * Waechter: Mouseover am Issue-Benachrichtigungs-Badge.
 *
 * Der Badge sagte "3" und sonst nichts. Wer wissen wollte, WAS passiert ist,
 * musste den Dialog oeffnen – womit alles als gesehen gilt, der Badge weg ist
 * und die Frage "was war das nochmal?" nicht mehr beantwortbar. Das Panel
 * zeigt es, OHNE etwas als gesehen zu markieren.
 *
 * Gemessen wird das ECHTE Modul in jsdom (issues.js wird ausgefuehrt, der
 * Hover wirklich ausgeloest) – nicht der Quelltext gelesen. Die zwei Dinge,
 * die nur der Quelltext hergibt (CSS-Regeln, i18n-Paare), stehen am Ende und
 * sind als solche gekennzeichnet.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;

function check(bed, text, extra) {
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (extra ? ' – ' + extra : '')); }
}
function section(t) { console.log('\n═══ ' + t); }

const ISS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/issues.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

// ── Testbett ───────────────────────────────────────────────────────────────
// ⚠ url: ist Pflicht – auf about:blank ist localStorage unbenutzbar und das
// Modul saehe ein fehlendes Token, das im Browser da ist (Register).
function bett(antwort) {
    const dom = new JSDOM(
        `<!DOCTYPE html><body>
           <button id="pt-issues-btn" title="Issues / Feedback">I</button>
         </body>`,
        { url: 'https://x.test/portal', runScripts: 'outside-only', pretendToBeVisual: true });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    // Uebersetzungen: die echten Werte aus i18n.js waeren ein zweiter Parser.
    // Der Waechter prueft die SCHLUESSEL – die Paare DE/EN unten separat.
    w.t = (k) => ({
        'issues.notif_title': 'Benachrichtigungen',
        'issues.notif_edited': 'bearbeitet',
        'issues.notif_new': 'neu',
        'issues.notif_from': 'von',
        'issues.notif_more': '… und {n} weitere',
        'issues.notif_hint': 'Eintrag anklicken, um die Meldung zu öffnen',
        'issues.status_open': 'Offen',
        'issues.status_in_progress': 'In Arbeit',
        'issues.status_closed': 'Geschlossen',
        'issues.none_found': 'Keine Issues gefunden.',
        'common.close': 'Schliessen',
    })[k] || k;
    w.JarvisIcons = { trash: () => '<svg></svg>' };

    const rufe = [];
    w.fetch = (url, opt) => {
        rufe.push({ url: String(url).split('?')[0], method: (opt && opt.method) || 'GET' });
        const pfad = String(url).split('?')[0];
        if (pfad === '/api/issues/notifications') {
            return Promise.resolve({ ok: true, json: () => Promise.resolve(antwort) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    };
    // jsdom rechnet kein Layout – getBoundingClientRect liefert ueberall 0.
    // Fuer die Klammerung braucht es plausible Masse.
    w.Element.prototype.getBoundingClientRect = function () {
        if (this.classList && this.classList.contains('jv-iss-tip')) {
            return { left: 0, top: 0, right: 360, bottom: 300, width: 360, height: 300 };
        }
        return { left: 980, top: 10, right: 1000, bottom: 26, width: 20, height: 16 };
    };
    Object.defineProperty(w, 'innerWidth', { value: 1000, configurable: true });
    Object.defineProperty(w, 'innerHeight', { value: 800, configurable: true });

    w.eval(ISS_JS);
    return { w, d: w.document, rufe };
}

const warten = () => new Promise(r => setTimeout(r, 30));

function posten(n, art) {
    const out = [];
    for (let i = 0; i < n; i++) {
        out.push(art === 'new'
            ? { id: 'id' + i, title: 'Fremde Meldung ' + i, kind: 'new',
                status: 'open', author: 'nexus\\max.muster', ts: '2026-08-28T09:0' + i + ':00' }
            : { id: 'id' + i, title: 'Meine Meldung ' + i, kind: 'edited',
                status: 'in_progress', ts: '2026-08-28T09:0' + i + ':00',
                comment: 'Wir kuemmern uns darum.' });
    }
    return out;
}

(async () => {
    // ═══════════════════════════════════════════════════════════════════════
    section('1) Ohne Benachrichtigung gibt es kein Panel');
    // ═══════════════════════════════════════════════════════════════════════
    {
        const { w, d } = bett({ ok: true, count: 0, items: [] });
        await warten();
        const badge = d.querySelector('.jv-iss-notif');
        check(!!badge, 'der Badge existiert im Knopf');
        check(badge.style.display === 'none', 'und ist bei 0 unsichtbar');
        badge.dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        check(!tip || tip.style.display === 'none',
              'Hover bei 0 zeigt NICHTS – ein leeres Panel waere eine Enttaeuschung');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('2) Hover zeigt die Liste – und markiert NICHTS als gesehen');
    // ═══════════════════════════════════════════════════════════════════════
    {
        const { w, d, rufe } = bett({ ok: true, count: 3, items: posten(3, 'edited') });
        await warten();
        const badge = d.querySelector('.jv-iss-notif');
        check(badge.style.display !== 'none' && badge.textContent === '3',
              'der Badge zeigt die Zahl');

        badge.dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        check(!!tip && tip.style.display === 'block', 'das Panel erscheint');
        check(tip.parentElement === d.body,
              'es haengt direkt an <body> – sonst klemmt es im Stapelkontext der Titelleiste');
        const zeilen = tip.querySelectorAll('.jv-iss-tip-row');
        check(zeilen.length === 3, 'mit einer Zeile je Benachrichtigung', zeilen.length);
        check(/Meine Meldung 0/.test(tip.textContent), 'der Titel steht drin');
        check(/In Arbeit/.test(tip.textContent), 'der Status ebenfalls');
        check(/Wir kuemmern uns/.test(tip.textContent),
              'und der Kommentar – er IST die Nachricht an den Melder');

        // ⚠ DAS IST DER KERN: Hovern darf den Badge NICHT loeschen.
        check(!rufe.some(r => r.url === '/api/issues/notifications/seen'),
              'Hovern meldet NICHTS als gesehen');
        check(badge.style.display !== 'none', 'und der Badge steht noch');

        badge.dispatchEvent(new w.MouseEvent('mouseleave'));
        await new Promise(r => setTimeout(r, 300));
        check(tip.style.display === 'none', 'Verlassen schliesst es wieder');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('3) Der Weg vom Badge ins Panel darf nicht abreissen');
    // ═══════════════════════════════════════════════════════════════════════
    // Ohne die Schliess-Frist und das mouseenter am Panel waere keine Zeile je
    // anklickbar – zwischen Badge und Panel liegen ein paar Pixel Zwischenraum.
    {
        const { w, d } = bett({ ok: true, count: 2, items: posten(2, 'edited') });
        await warten();
        const badge = d.querySelector('.jv-iss-notif');
        badge.dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        badge.dispatchEvent(new w.MouseEvent('mouseleave'));
        tip.dispatchEvent(new w.MouseEvent('mouseenter'));   // Zeiger wandert hinein
        await new Promise(r => setTimeout(r, 300));
        check(tip.style.display === 'block',
              'das Panel bleibt offen, solange der Zeiger darin ist');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('4) Klick auf eine Zeile oeffnet GENAU diese Meldung');
    // ═══════════════════════════════════════════════════════════════════════
    {
        const { w, d, rufe } = bett({ ok: true, count: 3, items: posten(3, 'edited') });
        await warten();
        const badge = d.querySelector('.jv-iss-notif');
        badge.dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        tip.querySelectorAll('.jv-iss-tip-row')[1].dispatchEvent(
            new w.MouseEvent('click', { bubbles: true }));
        await warten();
        check(rufe.some(r => r.url === '/api/issues/id1'),
              'die Detailansicht der angeklickten Meldung wird geladen',
              JSON.stringify(rufe.map(r => r.url)));
        check(rufe.some(r => r.url === '/api/issues/notifications/seen' && r.method === 'POST'),
              'und JETZT gilt alles als gesehen (Oeffnen, nicht Hovern)');
        check(tip.style.display === 'none', 'das Panel schliesst sich dabei');
        check(!!w.JarvisIssues.openIssue, 'openIssue ist oeffentlich nutzbar');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('5) Der Deckel wird BEZIFFERT, nicht verschwiegen');
    // ═══════════════════════════════════════════════════════════════════════
    // Der Server ueberträgt hoechstens 12 Eintraege. Ohne die Restzahl haelt
    // der Benutzer die Liste fuer vollstaendig, waehrend der Badge 30 zeigt.
    {
        const { w, d } = bett({ ok: true, count: 30, items: posten(12, 'new') });
        await warten();
        const badge = d.querySelector('.jv-iss-notif');
        badge.dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        check(tip.querySelectorAll('.jv-iss-tip-row').length === 12, '12 Zeilen gezeichnet');
        const mehr = tip.querySelector('.jv-iss-tip-more');
        check(!!mehr && /18/.test(mehr.textContent),
              'und "… und 18 weitere" darunter', mehr && mehr.textContent);
        check(/\(30\)/.test(tip.querySelector('.jv-iss-tip-h').textContent),
              'die Kopfzeile nennt die volle Zahl');
        check(/von[\s\S]*max\.muster/.test(tip.textContent),
              'bei fremden Meldungen steht der Melder dabei');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('6) Fremdtext wird maskiert');
    // ═══════════════════════════════════════════════════════════════════════
    // Titel, Melder und Kommentar kommen aus einer Meldung, die jemand anders
    // geschrieben hat. Das Panel steht auf JEDER Seite – auch dort, wo das
    // Sitzungstoken im localStorage liegt.
    {
        const boese = '<img src=x onerror="window.__ANGRIFF=1">';
        const { w, d } = bett({ ok: true, count: 1, items: [{
            id: 'x1', title: boese, kind: 'new', status: 'open',
            author: boese, ts: '2026-08-28T09:00:00' }] });
        await warten();
        d.querySelector('.jv-iss-notif').dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        check(tip.querySelectorAll('img').length === 0, 'kein <img> aus dem Titel im DOM');
        check(w.__ANGRIFF === undefined, 'und nichts davon ausgefuehrt');
        check(/onerror/.test(tip.textContent), 'der Text steht als TEXT da');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('7) Das Panel folgt dem Stand – es behauptet nichts');
    // ═══════════════════════════════════════════════════════════════════════
    {
        const dom = bett({ ok: true, count: 2, items: posten(2, 'edited') });
        const { w, d } = dom;
        await warten();
        d.querySelector('.jv-iss-notif').dispatchEvent(new w.MouseEvent('mouseenter'));
        await warten();
        const tip = d.querySelector('.jv-iss-tip');
        check(tip.querySelectorAll('.jv-iss-tip-row').length === 2, 'zwei Zeilen offen');

        // Der 60-s-Takt bringt einen neuen Stand, waehrend das Panel offen ist.
        w.fetch = (url) => Promise.resolve({
            ok: true,
            json: () => Promise.resolve(String(url).split('?')[0] === '/api/issues/notifications'
                ? { ok: true, count: 4, items: posten(4, 'edited') } : { ok: true }),
        });
        await w.JarvisIssues.refreshBadge();
        await warten();
        check(tip.querySelectorAll('.jv-iss-tip-row').length === 4,
              'das offene Panel folgt dem neuen Stand');

        // …und bei 0 verschwindet es mitsamt dem Badge.
        w.fetch = (url) => Promise.resolve({
            ok: true,
            json: () => Promise.resolve(String(url).split('?')[0] === '/api/issues/notifications'
                ? { ok: true, count: 0, items: [] } : { ok: true }),
        });
        await w.JarvisIssues.refreshBadge();
        await warten();
        check(tip.style.display === 'none',
              'bei 0 schliesst es sich – eine Liste ohne Badge waere eine Behauptung');
        w.close();
    }

    // ═══════════════════════════════════════════════════════════════════════
    section('8) Quelltext: was ein DOM-Test nicht sehen kann');
    // ═══════════════════════════════════════════════════════════════════════
    // jsdom rechnet kein Layout und wertet <style> nicht aus – die zwei
    // Eigenschaften, an denen dieses Panel steht und faellt, werden deshalb an
    // der REGEL geprueft (Register).
    const css = ISS_JS.slice(ISS_JS.indexOf('.jv-iss-tip{'));
    const block = css.slice(0, css.indexOf('}') + 1);
    check(/background:var\(--bg-secondary\)/.test(block),
          'das Panel hat eine DECKENDE Flaeche – darunter liegt Seiteninhalt');
    check(!/rgba\(var\(--fg-rgb\),\s*\.0/.test(block),
          'und keine halbtransparente stattdessen');
    check(/position:fixed/.test(block), 'es ist `fixed` positioniert');
    const zTip = (block.match(/z-index:(\d+)/) || [])[1];
    check(zTip && Number(zTip) < 99999,
          'sein z-index liegt UNTER dem Modal – oeffnet der Dialog, gehoert er nach vorn',
          zTip);

    // Kontrast: die naheliegenden Signalfarben sind bei 9px unlesbar
    // (weiss auf var(--warning) = 2,15:1, weiss auf #3b82f6 = 3,68:1 – im
    // echten Chrome gemessen). Der Waechter haelt fest, dass sie NICHT
    // zurueckkommen; die Zahlen selbst kann jsdom nicht rechnen.
    const pillen = ISS_JS.slice(ISS_JS.indexOf('.jv-iss-tip-k{'),
                                ISS_JS.indexOf('.jv-iss-tip-sub{'));
    check(!/var\(--warning\)/.test(pillen),
          'die Marken benutzen NICHT var(--warning) – dort gemessen 2,15:1');
    check(!/#3b82f6/.test(pillen), 'und nicht #3b82f6 – dort 3,68:1');
    check(/#b45309/.test(pillen) && /#2563eb/.test(pillen),
          'sondern die abgedunkelten Toene (5,05:1 / 5,12:1)');
    check(!/\.jv-iss-tip-(more|hint)\{color:var\(--text-muted\)/.test(ISS_JS),
          'und die Hinweiszeilen nicht --text-muted (3,72:1 bei 10px)');

    // Der Badge muss den Zeiger annehmen, sonst gibt es gar kein Mouseover.
    const nb = ISS_JS.slice(ISS_JS.indexOf('.jv-iss-notif{'));
    check(/pointer-events:auto/.test(nb.slice(0, nb.indexOf('}') + 1)),
          'der Badge nimmt den Zeiger an (frueher pointer-events:none)');
    // Leerer title am Badge: sonst zeigt der Browser ZUSAETZLICH den nativen
    // Tooltip des Knopfes darunter.
    check(/setAttribute\('title',\s*''\)/.test(ISS_JS),
          'der Badge traegt einen LEEREN title – sonst zwei Kaesten uebereinander');

    // i18n: jeder benutzte Schluessel muss in DE UND EN stehen.
    // ⚠ Gesucht wird das STRING-LITERAL, nicht der Aufruf `window.t('…')`:
    // zwei der Schluessel stehen in einem Ternaer (`t(neu ? a : b)`) und
    // fielen sonst still aus der Pruefung – der Waechter waere gruen, ohne sie
    // je angesehen zu haben.
    const benutzt = [...ISS_JS.matchAll(/'(issues\.notif_[a-z_]+)'/g)].map(m => m[1]);
    check([...new Set(benutzt)].length >= 6,
          'das Modul benutzt die neuen i18n-Schluessel', [...new Set(benutzt)].join(','));
    [...new Set(benutzt)].forEach(k => {
        const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length;
        check(n === 2, k + ' ist in DE und EN hinterlegt', n);
    });
    check(/\{n\}/.test(I18N.slice(I18N.indexOf("'issues.notif_more'"))),
          'der Restzahl-Text traegt den Platzhalter {n}');

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => {
    // ⚠ Ein Absturz ist NICHT dasselbe wie ein Fehlschlag – Exit 2, sonst
    // sieht "konnte nicht laufen" wie "bestanden" aus (Register).
    console.error('ABBRUCH: ' + (e && e.stack || e));
    process.exit(2);
});
