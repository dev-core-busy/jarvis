/* Sitzungsmodul (frontend/js/sitzung.js) in ein jsdom-Fenster laden.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT – gemessen am 2026-10-05: der Umbau
 * „Sitzungstoken aus EINER Quelle" (8d082990, einen Tag alt) hat ACHT Waechter
 * STILL GETOETET. Sie massen zusammen 495 Pruefungen und massen danach NULL:
 *
 *     test_confluence_addon_ui   38 -> 0      test_portal_kacheln_ui   32 -> 0
 *     test_gear_badge_ui         87 -> 0      test_topbar_symbole_ui  106 -> 0
 *     test_jira_addon_ui         96 -> 0      test_update_pill_ui      26 -> 0
 *     test_mail_sig_ui           89 -> 0      test_wissen_audit_ui     21 -> 0
 *
 * Seit dem Umbau liest jedes Frontend-Modul den Token ueber
 * `window.JarvisSitzung.token()`. Fehlt das Modul im Pruefstand, wirft der
 * ERSTE Abruf einen TypeError („Cannot read properties of undefined (reading
 * 'token')"). Je nach Ort ist die Folge:
 *   - unbehandelt  -> Stacktrace und Exit 1, OHNE Bilanzzeile
 *   - im `catch`   -> leere Liste, kein Fehler, trivial gruene Pruefungen
 * Exit 1 ist die Sprache, in der ein Waechter „ich beisse" sagt – „konnte
 * nicht laufen" war davon nicht zu unterscheiden. Genau dieselbe Klasse wie
 * die jsdom-Suchorte (siehe lib/jsdom_laden.js, 2026-09-30).
 *
 * ⚠ DIE MILDERUNG IM PRODUKTIVCODE IST AUSDRUECKLICH VERWORFEN. Ein
 * `window.JarvisSitzung && window.JarvisSitzung.token()` in den Modulen laesst
 * ein fehlendes Skript wie „nicht angemeldet" aussehen – damit endeten 23 von
 * 23 Waechtern mit Exit 0, waehrend ihre PRUEFZAHL einbrach (`test_email_ui`
 * 279 -> 4). Die Begruendung steht im Kopf von frontend/js/sitzung.js. Der
 * Pruefstand muss das Modul also LADEN, nicht wegdefinieren.
 *
 * Aufruf (vor dem eval der Seiten-Module – im Browser ist sitzung.js das ERSTE
 * Skript jeder Seite):
 *     require('./lib/sitzung_laden')(window);
 *     require('./lib/sitzung_laden')(window, { token: 'testtoken' });
 *
 * `token` legt den Wert unter `jarvis_token` ab. Ohne Angabe liefert `token()`
 * einen Leerstring – das ist „nicht angemeldet" und fuer die meisten
 * Pruefstaende richtig, weil sie ihre Abrufe ohnehin abfangen. Wo eine Seite
 * sich ohne Token selbst umleitet, gehoert der Token gesetzt.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const QUELLE = path.resolve(__dirname, "..", "..", "frontend", "js", "sitzung.js");

/** Laedt das ECHTE Modul in `window` und gibt `window.JarvisSitzung` zurueck.
 *
 *  ⚠ Positivkontrolle eingebaut: steht danach kein benutzbares
 *  `window.JarvisSitzung`, WIRFT diese Funktion. Ein Pruefstand, der das Modul
 *  zu laden glaubt und es nicht hat, ist genau der Fall, gegen den die Datei
 *  gebaut ist – er darf nicht still weiterlaufen. */
function laden(window, opt) {
    if (!window) throw new Error("sitzung_laden: kein window uebergeben");
    window.eval(fs.readFileSync(QUELLE, "utf8"));
    const s = window.JarvisSitzung;
    if (!s || typeof s.token !== "function") {
        throw new Error("sitzung_laden: " + QUELLE + " hat kein window.JarvisSitzung"
                        + " gesetzt (runScripts der JSDOM-Instanz pruefen)");
    }
    const token = opt && opt.token;
    if (token) {
        try {
            window.localStorage.setItem("jarvis_token", token);
        } catch (e) {
            throw new Error("sitzung_laden: localStorage nicht beschreibbar: " + e.message);
        }
    }
    return s;
}

module.exports = laden;
module.exports.laden = laden;
module.exports.quelle = () => QUELLE;
