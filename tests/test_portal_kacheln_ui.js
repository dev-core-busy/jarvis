#!/usr/bin/env node
/**
 * Portal-Kacheln: ein Fehlschlag darf nicht wie "keine Berechtigung" aussehen.
 *
 * GEMELDET (2026-08-25): "im laufenden Betrieb wird auf ECHT die Kachel Wissen
 * beim Benutzer nexus\andreas.bender oft nicht angezeigt, dann ist ein logout
 * und wieder login noetig."
 *
 * Der Abruf sah so aus:
 *
 *     fetch('/api/wissen/scope', {headers: H})
 *         .then(r => r.ok ? r.json() : null)
 *         .then(d => { if (d && d.groups.length) kachelZeigen(); })
 *         .catch(function(){});          // <- verschluckt ALLES
 *
 * Damit endeten vier voellig verschiedene Lagen im selben Bild – Kachel weg,
 * keine Meldung:
 *   * 401/403  = die Sitzung gilt nicht mehr (der Benutzer muesste sich neu
 *                anmelden, erfaehrt es aber nicht),
 *   * 5xx      = der Server konnte gerade nicht antworten,
 *   * Netzweg  = der Dienst startet neu (auf ECHT 101x in einer Woche),
 *   * 200 + [] = wirklich keine Berechtigung.
 * Nur der letzte Fall rechtfertigt eine fehlende Kachel.
 *
 * Geprueft wird das VERHALTEN am echten portal.html mit dem echten Inline-
 * Skript, nicht der Quelltext: ein grep saehe nicht, ob der Nachversuch
 * wirklich feuert.
 *
 *   node tests/test_portal_kacheln_ui.js
 */
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' - ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM, VirtualConsole;
try {
    const j = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');
    JSDOM = j.JSDOM; VirtualConsole = j.VirtualConsole;
} catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/portal.html');

/* Das Inline-Skript ist der geaenderte Teil. jsdom fuehrt bei
   runScripts:'outside-only' KEINE Seitenskripte aus – wir holen den Block
   heraus und werten ihn selbst aus, NACHDEM fetch und localStorage stehen
   (Register: `window.fetch` muss vor dem eval gesetzt sein, sonst bricht die
   IIFE ab, bevor sie irgendetwas verdrahtet). */
function inlineSkript() {
    const treffer = HTML.match(/<script>([\s\S]*?)<\/script>/g) || [];
    const kandidaten = treffer
        .map(s => s.replace(/^<script>/, '').replace(/<\/script>$/, ''))
        .filter(s => s.indexOf('/api/wissen/scope') !== -1);
    if (kandidaten.length !== 1) {
        console.log('ABBRUCH: Inline-Skript mit /api/wissen/scope nicht eindeutig gefunden ('
                    + kandidaten.length + ')');
        process.exit(2);
    }
    return kandidaten[0];
}
const INLINE = inlineSkript();

const SCOPE_OK = { ok: true, groups: [{ id: 'ibs', name: 'IBS' }], folders: [] };
const ME_OK = { username: 'nexus\\andreas.bender', is_admin: false, permissions: {} };

/**
 * Baut die Seite und laesst das echte Inline-Skript laufen.
 * `plan` legt je Aufruf von /api/wissen/scope fest, was passiert:
 *   {status: 200, body}  – normale Antwort
 *   {status: 401|403|500}
 *   'netz'               – fetch rejectet (Dienst startet neu)
 */
function baueSeite(plan) {
    const vc = new VirtualConsole();
    vc.on('jsdomError', () => {});   // "Not implemented: navigation" ist erwartet
    const dom = new JSDOM(HTML, {
        url: 'https://localhost/portal', runScripts: 'outside-only', virtualConsole: vc,
    });
    const { window } = dom;
    window.localStorage.setItem('jarvis_token', 'nexus\\andreas.bender:1:deadbeef');

    const rufe = [];
    let n = 0;
    const antwort = (status, body) => Promise.resolve({
        ok: status >= 200 && status < 300, status: status,
        json: () => Promise.resolve(body === undefined ? {} : body),
    });
    window.fetch = function (url) {
        const u = String(url).split('?')[0];
        rufe.push(u);
        if (u === '/api/wissen/scope') {
            const s = plan[Math.min(n++, plan.length - 1)];
            if (s === 'netz') return Promise.reject(new TypeError('Failed to fetch'));
            return antwort(s.status, s.body);
        }
        if (u === '/api/me') return antwort(200, ME_OK);
        return antwort(200, { ok: true });
    };
    let gesperrtGezeigt = false;
    window.SecurityIncidents = { fetchAndShowBlocked: () => { gesperrtGezeigt = true; } };

    window.eval(lies('frontend/js/i18n.js'));
    window.eval(INLINE);
    return {
        window,
        rufe,
        scopeRufe: () => rufe.filter(u => u === '/api/wissen/scope').length,
        gesperrt: () => gesperrtGezeigt,
        kachelSichtbar: () => {
            const c = window.document.getElementById('pt-card-wissen');
            return !!c && !c.classList.contains('hidden');
        },
        bannerSichtbar: () => {
            const b = window.document.getElementById('pt-load-banner');
            return !!b && b.style.display === '';
        },
        angemeldet: () => window.localStorage.getItem('jarvis_token') !== null,
        bannerText: () => (window.document.getElementById('pt-load-banner') || {}).textContent || '',
    };
}

const warte = (ms) => new Promise(r => setTimeout(r, ms));

async function main() {
    console.log('='.repeat(70));
    console.log('UI-Test Portal-Kacheln (jsdom, echtes portal.html + Inline-Skript)');
    console.log('='.repeat(70));

    /* ================================================================= */
    abschnitt('1. Normalfall: Berechtigung vorhanden');
    {
        const s = baueSeite([{ status: 200, body: SCOPE_OK }]);
        await warte(60);
        pruefe(s.kachelSichtbar(), 'Kachel erscheint');
        pruefe(!s.bannerSichtbar(), '... ohne Hinweisstreifen');
        pruefe(s.scopeRufe() === 1, '... mit genau EINEM Abruf (kein Nachfassen ohne Anlass)');
        pruefe(s.angemeldet(), '... und die Sitzung bleibt bestehen');
    }

    /* ================================================================= */
    abschnitt('2. 200 mit leerer Gruppenliste = wirklich keine Berechtigung');
    {
        const s = baueSeite([{ status: 200, body: { ok: true, groups: [] } }]);
        await warte(60);
        pruefe(!s.kachelSichtbar(), 'Kachel bleibt aus');
        pruefe(!s.bannerSichtbar(),
               '... und ZWAR OHNE Hinweis: hier ist der Zustand bekannt, nicht unklar');
        pruefe(s.scopeRufe() === 1, '... kein Nachfassen (die Antwort war gueltig)');
    }

    /* ================================================================= */
    abschnitt('3. Die Sitzung gilt nicht mehr -> abmelden statt schweigen');
    {
        const s = baueSeite([{ status: 401 }]);
        await warte(60);
        pruefe(!s.angemeldet(),
               '401: Token wird verworfen (der Benutzer landet auf der Loginseite)');
        pruefe(!s.kachelSichtbar(), '... Kachel bleibt aus');
        pruefe(s.scopeRufe() === 1, '... und es wird NICHT nachgefasst (das waere sinnlos)');
    }
    {
        const s = baueSeite([{ status: 403, body: { detail: 'NOT_AUTHORIZED' } }]);
        await warte(60);
        pruefe(!s.angemeldet(), '403 NOT_AUTHORIZED: Token wird ebenfalls verworfen');
        pruefe(!s.gesperrt(), '... und der Sperr-Bildschirm bleibt aus (falscher Anlass)');
    }
    {
        const s = baueSeite([{ status: 403, body: { detail: 'ACCOUNT_BLOCKED' } }]);
        await warte(60);
        pruefe(s.gesperrt(), '403 ACCOUNT_BLOCKED: Sperr-Bildschirm wird gezeigt');
        pruefe(s.angemeldet(),
               '... und die Sitzung bleibt – sonst saehe der Benutzer den Grund nie');
    }

    /* ================================================================= */
    abschnitt('4. Serverfehler und Neustart: EINMAL nachfassen');
    {
        const s = baueSeite([{ status: 500 }, { status: 200, body: SCOPE_OK }]);
        await warte(1800);
        pruefe(s.scopeRufe() === 2, 'nach 500 wird genau einmal nachgefasst');
        pruefe(s.kachelSichtbar(), '... der zweite Versuch bringt die Kachel');
        pruefe(!s.bannerSichtbar(), '... und kein Hinweis, weil es geklappt hat');
        pruefe(s.angemeldet(), '... die Sitzung bleibt unangetastet');
    }
    {
        // Der haeufigste Fall auf ECHT: der Dienst startet gerade neu.
        const s = baueSeite(['netz', { status: 200, body: SCOPE_OK }]);
        await warte(1800);
        pruefe(s.scopeRufe() === 2, 'auch ein NETZfehler wird nachgefasst');
        pruefe(s.kachelSichtbar(), '... und die Kachel kommt doch noch');
    }

    /* ================================================================= */
    abschnitt('5. Bleibt es dabei, wird der unbekannte Zustand GEMELDET');
    {
        const s = baueSeite([{ status: 500 }, { status: 500 }]);
        await warte(1800);
        pruefe(s.scopeRufe() === 2, 'genau zwei Versuche, dann Schluss (keine Schleife)');
        pruefe(!s.kachelSichtbar(),
               'die Kachel bleibt aus – unbekannt ist keine Berechtigung');
        pruefe(s.bannerSichtbar(), 'ABER der Hinweisstreifen erscheint');
        pruefe(s.angemeldet(),
               '... und der Benutzer wird NICHT abgemeldet (der Server war das Problem)');
        pruefe(/erneut/i.test(s.bannerText()),
               '... der Text nennt den Weg zurueck', s.bannerText());
    }
    {
        const s = baueSeite(['netz', 'netz']);
        await warte(1800);
        pruefe(s.bannerSichtbar(), 'dasselbe bei dauerhaftem Netzfehler');
    }

    /* ================================================================= */
    abschnitt('6. Die Regel gilt fuer ALLE Kacheln, nicht nur fuer Wissen');
    {
        const code = INLINE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
        /* Gezaehlt wird NUR im Umfeld der Kachel-Abrufe. Ein Waechter ueber das
           ganze Inline-Skript wuerde fremden Code messen: die Badge-Polls
           (`/api/userchat/unread`, `/api/tracks/...`) duerfen ihren Fehlschlag
           weiter schlucken – ein Badge entscheidet ueber nichts, und ein Poll,
           der alle 30 s die Sitzung beenden koennte, waere die schlechtere
           Loesung. Ein KACHEL-Abruf dagegen behauptet eine Berechtigung. */
        const nachStelle = (marke) => {
            const i = code.indexOf(marke);
            return i === -1 ? '' : code.slice(i, i + 700);
        };
        const stille = ["holeGeschuetzt('/api/me')",
                        "holeGeschuetzt('/api/wissen/scope')",
                        "holeGeschuetzt('/api/support/status')"]
            .filter(m => /\.catch\(function\s*\(\)\s*\{\s*\}\s*\)/.test(nachStelle(m))).length;
        pruefe(code.indexOf("holeGeschuetzt('/api/me')") !== -1,
               '/api/me laeuft ueber den Helfer (der 401-Fall fehlte dort ebenfalls)');
        pruefe(code.indexOf("holeGeschuetzt('/api/wissen/scope')") !== -1,
               '/api/wissen/scope laeuft ueber den Helfer');
        pruefe(code.indexOf("holeGeschuetzt('/api/support/status')") !== -1,
               '/api/support/status ebenfalls (gleiche Fehlerklasse)');
        pruefe(stille === 0,
               'kein stilles .catch(function(){}) mehr an diesen Abrufen', String(stille));
    }

    /* ================================================================= */
    abschnitt('7. Text in beiden Sprachen');
    {
        const i18n = lies('frontend/js/i18n.js');
        pruefe((i18n.match(/'portal\.load_failed'/g) || []).length === 2,
               'portal.load_failed in DE und EN');
        const s = baueSeite([{ status: 500 }, { status: 500 }]);
        await warte(1800);
        const de = s.bannerText();
        s.window.setLang ? s.window.setLang('en') : null;
        pruefe(de.length > 20 && de.indexOf('undefined') === -1,
               'der Streifen traegt einen echten Text', de);
    }

    console.log('\n' + '='.repeat(70));
    console.log('Ergebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
}

main();
