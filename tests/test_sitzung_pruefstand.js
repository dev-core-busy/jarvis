#!/usr/bin/env node
/* Waechter: ein Pruefstand, der ein Frontend-Modul AUSFUEHRT, muss sitzung.js laden.
 *
 * ⚠ DER BEZAHLTE VORFALL (2026-10-05): der Umbau „Sitzungstoken aus EINER
 * Quelle" (8d082990) hat ACHT Waechter STILL GETOETET – zusammen 495
 * Pruefungen, die danach NULL massen:
 *
 *     test_confluence_addon_ui   38 -> 0      test_portal_kacheln_ui   32 -> 0
 *     test_gear_badge_ui         87 -> 0      test_topbar_symbole_ui  106 -> 0
 *     test_jira_addon_ui         96 -> 0      test_update_pill_ui      26 -> 0
 *     test_mail_sig_ui           89 -> 0      test_wissen_audit_ui     21 -> 0
 *
 * Seit dem Umbau liest jedes Modul den Token ueber `window.JarvisSitzung`.
 * Fehlt das Modul im Fenster, wirft der erste Abruf einen TypeError; je nach
 * Ort endet der Lauf mit Exit 1 OHNE Bilanzzeile (von „ich beisse" nicht zu
 * unterscheiden) oder die Pruefungen werden trivial gruen. Dieselbe Klasse wie
 * die jsdom-Suchorte vom 2026-09-30 – damals 31 von 55 Dateien.
 *
 * GEPRUEFT WIRD DIE REGEL, NICHT EINE LISTE. Eine gepflegte Namensliste der
 * acht Faelle waere an dem Tag unvollstaendig, an dem jemand einen neunten
 * Pruefstand schreibt – und die fehlende Zeile meldet sich nicht.
 *
 * Die Regel: fuehrt ein Pruefstand ein Modul aus `frontend/js/` AUS, das
 * `window.JarvisSitzung` liest, dann muss er `sitzung.js` laden. „Nur als TEXT
 * lesen" zaehlt NICHT – viele Waechter lesen eine Datei fuer eine
 * Quelltext-Pruefung, ohne sie je auszufuehren; die brauchen das Modul nicht,
 * und wer sie mitmeldet, baut einen Waechter, den man abschaltet.
 *
 * Lauf:  node tests/test_sitzung_pruefstand.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const TESTS = __dirname;
const FJS = path.join(ROOT, 'frontend', 'js');

let ok = 0, fail = 0;
function pruefe(bed, titel, detail) {
    if (bed) { ok++; console.log('  ✅ ' + titel); }
    else { fail++; console.log('  ❌ ' + titel + (detail ? '\n      ' + detail : '')); }
}
const abschnitt = (t) => console.log('\n' + t);

/* Kommentarbereiche durch gleich viele Leerzeichen ersetzen – ein Waechter,
   der seine eigene Begruendung liest, prueft nichts. Laengentreu, damit kein
   Offset verrutscht. */
const _leer = (t) => String(t).replace(/[^\n]/g, ' ');
const ohneKommentar = (s) => String(s)
    .replace(/\/\*[\s\S]*?\*\//g, _leer)
    .replace(/^[ \t]*\/\/.*$/gm, _leer);

/* ── 1. Welche Module lesen den Sitzungstoken? ─────────────────────────── */
abschnitt('1 – Module, die window.JarvisSitzung lesen');

const liestToken = new Set(
    fs.readdirSync(FJS)
      .filter((f) => f.endsWith('.js'))
      .filter((f) => f !== 'sitzung.js')
      .filter((f) => /JarvisSitzung/.test(ohneKommentar(fs.readFileSync(path.join(FJS, f), 'utf8'))))
);
pruefe(liestToken.size > 0,
    'es gibt ueberhaupt token-lesende Module (' + liestToken.size + ')');
pruefe(/window\.JarvisSitzung\s*=/.test(fs.readFileSync(path.join(FJS, 'sitzung.js'), 'utf8')),
    'sitzung.js setzt window.JarvisSitzung (die Quelle existiert)');

/* ── 2. Welche Pruefstaende FUEHREN so ein Modul AUS? ──────────────────── */
abschnitt('2 – Pruefstaende, die ein solches Modul ausfuehren');

/* Zwei Gestalten kommen im Projekt vor:
 *   const NAME = fs.readFileSync(... 'frontend/js/mod.js' ...);  ... w.eval(NAME)
 *   window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/mod.js'), 'utf8'))
 * Die erste braucht die Bindung, die zweite steht direkt im eval. */
const PFAD_RE = /frontend\/js\/([A-Za-z0-9_]+)\.js/g;

function ausgefuehrteModule(quelle) {
    const s = ohneKommentar(quelle);
    const treffer = new Set();

    // (a) eval(...) mit dem Pfad DIREKT im Aufruf
    const evalRe = /\beval\s*\(/g;
    let m;
    while ((m = evalRe.exec(s))) {
        // Argumentliste bis zur passenden Klammer schneiden (kein festes Fenster:
        // ein zu kleines schneidet den Pfad ab, ein zu grosses greift in den
        // naechsten Aufruf – beides schon bezahlt).
        let tiefe = 0, i = m.index + m[0].length - 1, ende = -1;
        for (; i < s.length; i++) {
            if (s[i] === '(') tiefe++;
            else if (s[i] === ')' && --tiefe === 0) { ende = i; break; }
        }
        const arg = s.slice(m.index, ende < 0 ? s.length : ende + 1);
        let p;
        const re = new RegExp(PFAD_RE.source, 'g');
        while ((p = re.exec(arg))) treffer.add(p[1] + '.js');
        // (b) Bezeichner im eval -> ueber eine Bindung aufloesen.
        //
        // ⚠ NUR DER GANZE MODULINHALT ZAEHLT, kein Ausschnitt. Viele Waechter
        // SCHNEIDEN eine einzelne Funktion heraus (`w.eval(CHATLIB.slice(a,b))`)
        // und fuehren damit gerade NICHT die Modulebene aus, auf der der Token
        // gelesen wird – die brauchen sitzung.js nicht. Die erste Fassung dieses
        // Waechters zaehlte sie mit und meldete fuenf Pruefstaende, die
        // nachweislich gruen durchlaufen (chart_theme, chat_pdf, cleanup_alle,
        // viol_anzeige, welcome_examples). Ein Waechter mit Fehlalarmen wird
        // abgeschaltet, nicht gelesen. Erkennungsmerkmal: ein Punkt direkt
        // hinter dem Namen ist ein Zugriff auf eine Eigenschaft (`.slice`,
        // `.indexOf`), kein Uebergeben des Moduls.
        const namen = /([A-Za-z_$][A-Za-z0-9_$]*)\s*(\.?)/g;
        let nm;
        while ((nm = namen.exec(arg))) {
            if (nm[2] === '.') continue;          // Ausschnitt, nicht das Modul
            const bind = new RegExp(
                '(?:const|let|var)\\s+' + nm[1]
                + '\\s*=\\s*fs\\.readFileSync\\([^;]*?frontend/js/([A-Za-z0-9_]+)\\.js');
            const b = bind.exec(s);
            if (b) treffer.add(b[1] + '.js');
        }
    }

    /* (c) DIE SCHLEIFE UEBER EINE PFADLISTE – nachgetragen am 2026-10-05, weil
       (a)+(b) sie NICHT sahen und damit drei echte Faelle durchliessen:

           for (const f of ['frontend/js/i18n.js', ..., 'frontend/js/ai_mouse.js'])
               w.eval(fs.readFileSync(f, 'utf8'));

       Der Pfad steht in der LISTE, nicht im eval – im eval steht nur die
       Schleifenvariable. Gekostet hat die Luecke test_ai_mouse_ui (61 -> 29 OK
       bei 13 FAIL), test_ai_mouse_freigabe_ui (25 -> 0 OK) und latent
       test_am_bauhinweis_ui. Besonders tueckisch: dort faengt ein try/catch den
       Fehler und schreibt ihn als 'LADEFEHLER ...' ins Protokoll – der Lauf hat
       also eine BILANZZEILE und sieht nach einem echten Befund aus.

       Erkennungsmerkmal ist ein `eval`, dessen `readFileSync`-Pfad KEIN Literal
       ist. Dann zaehlen alle Modul-Literale der Datei. Am Bestand gemessen:
       19 Treffer, davon laden 16 sitzung.js bereits von sich aus – die Regel
       beschreibt also den Hausgebrauch und erfindet ihn nicht. */
    if (/\beval\s*\([^)]*readFileSync\s*\(\s*[A-Za-z_$]/.test(s)) {
        let p;
        const re = new RegExp(PFAD_RE.source, 'g');
        while ((p = re.exec(s))) treffer.add(p[1] + '.js');
    }
    return treffer;
}

const dateien = fs.readdirSync(TESTS).filter((f) => /^test_.*\.js$/.test(f));
const verstoesse = [];
let mitAusfuehrung = 0;

for (const f of dateien) {
    if (f === path.basename(__filename)) continue;
    const quelle = fs.readFileSync(path.join(TESTS, f), 'utf8');
    const module = [...ausgefuehrteModule(quelle)].filter((m) => liestToken.has(m));
    if (!module.length) continue;
    mitAusfuehrung++;
    // Geladen gilt: ueber den gemeinsamen Helfer ODER direkt die Datei.
    //
    // ⚠ OHNE KOMMENTARE PRUEFEN. Die erste Fassung las `quelle` im Rohzustand –
    // und jeder reparierte Pruefstand traegt einen Kommentar, der auf
    // `tests/lib/sitzung_laden.js` VERWEIST. Die Gegenprobe (Aufruf samt
    // require entfernt, Kommentar stehen gelassen) blieb deshalb GRUEN: der
    // Waechter las seine eigene Begruendung. Genau der Fehler, der im Projekt
    // schon siebzehnmal bezahlt wurde.
    const code = ohneKommentar(quelle);
    const laedt = /lib\/sitzung_laden/.test(code) || /frontend\/js\/sitzung\.js/.test(code);
    if (!laedt) verstoesse.push(f + '  ->  ' + module.sort().join(', '));
}

pruefe(mitAusfuehrung > 0,
    'Positivkontrolle: es werden ueberhaupt Module ausgefuehrt (' + mitAusfuehrung + ' Pruefstaende)');
pruefe(verstoesse.length === 0,
    'jeder Pruefstand, der ein token-lesendes Modul ausfuehrt, laedt sitzung.js',
    verstoesse.join('\n      '));

/* ── 3. Der gemeinsame Helfer ist die EINE Quelle ──────────────────────── */
abschnitt('3 – Der Helfer traegt eine Positivkontrolle');

const helfer = fs.readFileSync(path.join(TESTS, 'lib', 'sitzung_laden.js'), 'utf8');
const hCode = ohneKommentar(helfer);
pruefe(/sitzung\.js/.test(hCode),
    'der Helfer nennt die ECHTE Datei frontend/js/sitzung.js');
pruefe(!/JarvisSitzung\s*=\s*\{/.test(hCode),
    'er baut KEINE Attrappe (eine Attrappe prueft die eigene Annahme)');

/* ⚠ HIER WIRD AUSGEFUEHRT, NICHT GESUCHT. Die erste Fassung prueste
   `/throw new Error/` im Quelltext – und blieb gruen, als die Gegenprobe genau
   den entscheidenden Wurf durch `return null` ersetzte: die Datei enthaelt
   WEITERE `throw new Error` (fehlendes window, gesperrter localStorage), das
   Muster traf also einen anderen. Ein VORKOMMEN ist keine Aussage ueber die
   WIRKUNG. Gemessen wird deshalb das Verhalten an zwei Fenster-Attrappen. */
const sitzungLaden = require('./lib/sitzung_laden');

// (a) Ein Fenster, in dem das eval WIRKUNGSLOS bleibt: danach steht kein
//     JarvisSitzung da – der Helfer MUSS werfen, nicht still zurueckkehren.
let warf = false;
try {
    sitzungLaden({ eval: () => {}, localStorage: { setItem: () => {} } });
} catch (e) { warf = true; }
pruefe(warf, 'er WIRFT, wenn danach kein benutzbares window.JarvisSitzung steht');

// (b) Gegenkontrolle: wo das Modul WIRKT, darf er nicht werfen – sonst waere
//     (a) trivial wahr (ein Helfer, der immer wirft, bestuende die Probe).
let sauber = false, wert = null;
try {
    const attrappe = {
        localStorage: {
            _d: {},
            setItem(k, v) { this._d[k] = v; },
            getItem(k) { return this._d[k] || null; },
        },
    };
    attrappe.eval = (quelltext) => {
        // Das ECHTE sitzung.js laeuft hier – es braucht nur window + localStorage.
        new Function('window', 'localStorage', quelltext)(attrappe, attrappe.localStorage);
    };
    wert = sitzungLaden(attrappe, { token: 'probe-token' });
    sauber = !!wert && typeof wert.token === 'function';
} catch (e) { sauber = false; wert = e.message; }
pruefe(sauber, 'Gegenkontrolle: mit wirkendem Modul wirft er NICHT', String(wert));
pruefe(sauber && wert.token() === 'probe-token',
    'und der uebergebene Token ist ueber token() lesbar',
    sauber ? String(wert.token()) : 'nicht ermittelbar');

/* ── Bilanz ───────────────────────────────────────────────────────────── */
console.log('\n' + '='.repeat(70));
console.log(fail === 0
    ? `ERGEBNIS: ${ok}/${ok} Pruefungen bestanden`
    : `ERGEBNIS: ${ok} ok, ${fail} fehlgeschlagen`);
console.log('='.repeat(70));
process.exit(fail ? 1 : 0);
