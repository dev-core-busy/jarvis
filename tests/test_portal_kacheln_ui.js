#!/usr/bin/env node
/**
 * Portal-Kacheln: ein Fehlschlag darf nicht wie "keine Berechtigung" aussehen.
 *
 * GEMELDET (2026-08-25): "im laufenden Betrieb wird auf ECHT die Kachel Wissen
 * beim Benutzer firma\m.mustermann oft nicht angezeigt, dann ist ein logout
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
 *   * 200 + [] = kein Wissensbereich.
 * Seit 2026-10-15 zeigt auch der letzte Fall die Kachel ("Mein Gedaechtnis"
 * gibt es fuer jeden) – eine fehlende Kachel heisst jetzt: die
 * Antwort war nicht gueltig.
 *
 * Geprueft wird das VERHALTEN am echten portal.html mit dem echten Inline-
 * Skript, nicht der Quelltext: ein grep saehe nicht, ob der Nachversuch
 * wirklich feuert.
 *
 *   node tests/test_portal_kacheln_ui.js
 */
// Abbruchnetz aus EINER Quelle: ein Absturz endet mit Exit 2 statt mit
// Exit 1. Am 2026-10-05 lag diese Datei stumm brach, weil ein TypeError
// wie ein Befund aussah. Begruendung in tests/lib/bilanz.js.
require('./lib/bilanz')();

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
({ JSDOM, VirtualConsole } = require('./lib/jsdom_laden')());
const sitzungLaden = require('./lib/sitzung_laden');

const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/portal.html');
// Sitzungstoken: seit 8d082990 liegt die Schluesselkette an EINER Stelle
// (`window.JarvisSitzung`), und das Inline-Skript von portal.html liest sie
// ueber `tokenSchluessel()`. Das ECHTE Modul, keine Attrappe.
const SITZUNG = lies('frontend/js/sitzung.js');

/* Das Inline-Skript ist der geaenderte Teil. jsdom fuehrt bei
   runScripts:'outside-only' KEINE Seitenskripte aus – wir holen den Block
   heraus und werten ihn selbst aus, NACHDEM fetch und localStorage stehen
   (Register: `window.fetch` muss vor dem eval gesetzt sein, sonst bricht die
   IIFE ab, bevor sie irgendetwas verdrahtet). */
/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): der fruehere Inline-Block
   steht jetzt in js/portal_seite.js und wird an derselben Stelle per src
   eingebunden. Positivkontrolle: portal.html bindet GENAU diese Datei ein
   (sonst prueft der Test eine Datei, die die Seite nie laedt). */
function inlineSkript() {
    const tags = HTML.match(/<script src="\/static\/js\/portal_seite\.js\?v=\d+"><\/script>/g) || [];
    if (tags.length !== 1) {
        console.log('ABBRUCH: portal.html bindet portal_seite.js nicht genau einmal ein ('
                    + tags.length + ')');
        process.exit(2);
    }
    const quelle = lies('frontend/js/portal_seite.js');
    if (quelle.indexOf('/api/wissen/scope') === -1) {
        console.log('ABBRUCH: portal_seite.js enthaelt /api/wissen/scope nicht');
        process.exit(2);
    }
    return quelle;
}
const INLINE = inlineSkript();

const SCOPE_OK = { ok: true, groups: [{ id: 'ibs', name: 'IBS' }], folders: [] };
const ME_OK = { username: 'firma\\m.mustermann', is_admin: false, permissions: {} };

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
    // sitzung.js VOR den Modulen der Seite - im Browser ist sie das ERSTE
    // Skript, und die Module lesen den Token nur ueber window.JarvisSitzung.
    // Ohne sie wirft der erste Abruf, und der Lauf endet OHNE Bilanzzeile
    // (Begruendung und Messwerte: tests/lib/sitzung_laden.js).
    sitzungLaden(window);
    window.localStorage.setItem('jarvis_token', 'firma\\m.mustermann:1:deadbeef');

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

    window.eval(SITZUNG);   // vor allen Modulen - erstes <script> der Seite
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
    // Seit 2026-10-15 sieht JEDER Benutzer die Kachel: /wissen traegt den
    // Container "Mein Gedaechtnis" (eigenes Gedaechtnis), den es fuer
    // alle geben muss. Bis dahin hiess eine leere Gruppenliste "Kachel aus".
    abschnitt('2. 200 mit leerer Gruppenliste = Kachel trotzdem da (eigenes Wissen)');
    {
        const s = baueSeite([{ status: 200, body: { ok: true, groups: [] } }]);
        await warte(60);
        pruefe(s.kachelSichtbar(), 'Kachel erscheint auch ohne Wissensbereich');
        pruefe(!s.bannerSichtbar(),
               '... und ZWAR OHNE Hinweis: hier ist der Zustand bekannt, nicht unklar');
        pruefe(s.scopeRufe() === 1, '... kein Nachfassen (die Antwort war gueltig)');
    }
    abschnitt('2b. 200 mit ok:false = keine gueltige Antwort, keine Kachel');
    {
        const s = baueSeite([{ status: 200, body: { ok: false } }]);
        await warte(60);
        pruefe(!s.kachelSichtbar(), 'Kachel bleibt aus');
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
        /* Das Fenster endet am NAECHSTEN Abruf bzw. an der naechsten Funktion –
           kein festes Zeichenfenster: mit 700 Zeichen griff es am 2026-10-15,
           nachdem der Wissen-Abruf kuerzer wurde, in den Badge-Poll dahinter
           (refreshUnread) und meldete dessen bewusst stilles catch. */
        const nachStelle = (quelle, marke) => {
            const i = quelle.indexOf(marke);
            if (i === -1) return '';
            const rest = quelle.slice(i + marke.length);
            const enden = [rest.indexOf('holeGeschuetzt('), rest.search(/\n\s*function\s/)]
                .filter(n => n !== -1);
            return marke + (enden.length ? rest.slice(0, Math.min.apply(null, enden)) : rest);
        };
        const STILL = /\.catch\(function\s*\(\)\s*\{\s*\}\s*\)/;
        const MARKEN = ["holeGeschuetzt('/api/me')",
                        "holeGeschuetzt('/api/wissen/scope')",
                        "holeGeschuetzt('/api/support/status')"];
        const zaehle = (quelle) => MARKEN.filter(m => STILL.test(nachStelle(quelle, m))).length;
        // Positivkontrolle: ein stilles catch AN einem Kachel-Abruf wird gezaehlt,
        // eines in der Funktion dahinter nicht.
        const probe = "holeGeschuetzt('/api/wissen/scope').then(function(d){ x(); }).catch(function(){});\n"
                    + "    function refreshUnread(){ fetch('/u').catch(function(){}); }";
        const probeOhne = "holeGeschuetzt('/api/wissen/scope').then(function(d){ x(); });\n"
                    + "    function refreshUnread(){ fetch('/u').catch(function(){}); }";
        if (zaehle(probe) !== 1 || zaehle(probeOhne) !== 0) {
            console.log('ABBRUCH: Fenster-Messung erkennt die Probe nicht ('
                        + zaehle(probe) + '/' + zaehle(probeOhne) + ')');
            process.exit(2);
        }
        const stille = zaehle(code);
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
