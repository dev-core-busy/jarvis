#!/usr/bin/env node
/* Waechter: die Copilot-Verbindungsflaeche (frontend/js/copilot.js).
 *
 * Gemessen wird gegen die ECHTEN Dateien – echtes `settings.html`-Markup,
 * echtes `i18n.js`, echtes `copilot.js`. Eine Probeseite, die der Waechter
 * selbst baut, kann die Einbindung nicht pruefen (Register: `feedback_admin.js`
 * stand in keinem `<script>`-Tag und war 28/28 gruen, waehrend der Reiter im
 * Betrieb LEER geblieben waere).
 *
 * VIER ZUSAGEN, DIE HIER HAENGEN
 * 1. **Die Anzeige behauptet keinen Zustand, den sie nicht kennt.** Faellt die
 *    Auskunft aus, sagt sie das – sie zeigt nicht "nicht verbunden".
 * 2. **Jede fehlende Vorbedingung nennt die Stelle, an der sie haengt**
 *    (Skill, Entra-Anwendung, Internet-Freigabe). Ein Knopf, der mit 403
 *    antwortet, laesst den Benutzer raten.
 * 3. **Fremder Text wird escaped und keine fremde Adresse wird verlinkt**, die
 *    nicht https ist. Der Kontoname kommt aus einem Microsoft-Token, die
 *    Adresse von Microsoft – beides ist Fremdtext in einem innerHTML.
 * 4. **Der Abhol-Takt wird bei JEDEM Ende gestoppt.** Ein weiterlaufender
 *    Timer fragt endlos und haelt in jsdom den Prozess offen.
 *
 * Exit 2, wenn eine Positivkontrolle nicht messbar ist.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("./lib/jsdom_laden")();

const ROOT = path.resolve(__dirname, "..");
let ok = 0, fail = 0, bilanz = false;

function pruefe(bed, text) {
    if (bed) { ok++; console.log("  OK   " + text); }
    else { fail++; console.log("  FAIL " + text); }
}
function abbruch(text) {
    console.log("ABBRUCH (Exit 2): " + text);
    process.exit(2);
}
// Ein stiller Abbruch darf nicht als "beisst" gelesen werden – nur einen
// Exit 0 OHNE Bilanz anheben (Register).
process.on("exit", (code) => {
    if (!bilanz && code === 0) process.exitCode = 1;
});

// ─── Die echten Dateien ────────────────────────────────────────────────────
const MARKUP = fs.readFileSync(path.join(ROOT, "frontend", "settings.html"), "utf8");
const COPILOT_JS = fs.readFileSync(path.join(ROOT, "frontend", "js", "copilot.js"), "utf8");
const I18N_JS = fs.readFileSync(path.join(ROOT, "frontend", "js", "i18n.js"), "utf8");
const STYLE_CSS = fs.readFileSync(path.join(ROOT, "frontend", "css", "style.css"), "utf8");

// ─── 1. Einbindung und Markup ──────────────────────────────────────────────
console.log("1. Einbindung");
pruefe(/\/static\/js\/copilot\.js\?v=\d+/.test(MARKUP),
       "copilot.js ist in settings.html eingebunden (mit Cache-Buster)");
pruefe(MARKUP.includes('id="copilot-status-container"'),
       "der Container #copilot-status-container steht im Markup");
pruefe(MARKUP.includes('id="skcfg-copilot"'),
       "der Container #skcfg-copilot fuer die Kennungen steht im Markup");
pruefe(MARKUP.includes('data-settings-tab="copilot"'),
       "der Reiter-Knopf ist angelegt");
pruefe(/id="settings-tab-copilot"[^>]*class="settings-tab-content"/.test(MARKUP),
       "der Reiter-Inhalt traegt die Klasse settings-tab-content");

// ─── 2. Seite aufbauen, Module WIRKLICH laden ──────────────────────────────
function aufbauen() {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on("jsdomError", (e) => fehler.push(String(e && e.message || e)));
    const dom = new JSDOM(MARKUP, {
        url: "https://pruefstand.invalid/settings",
        runScripts: "outside-only",
        virtualConsole: vc,
    });
    const w = dom.window;
    global.window = w;
    global.document = w.document;
    // Node hat ein EIGENES globales fetch – ohne diese Zeile ginge der Aufruf
    // ins echte Netz, landete im catch, und die Messung praefte eine Kette,
    // die nie stattfand (Register).
    global.fetch = w.fetch = undefined;
    // Die Sitzung ist keine Attrappe des Moduls, nur der Token-Wert: copilot.js
    // ruft window.JarvisSitzung.token() bei JEDEM Aufruf, nicht beim Laden.
    w.JarvisSitzung = { token: () => "pruef-token" };
    w.eval(I18N_JS);
    w.eval(COPILOT_JS);
    return { dom, w, fehler };
}

const { dom: dom0, w: w0, fehler: fehler0 } = aufbauen();
console.log("2. Module laden");
if (fehler0.length) abbruch("jsdom meldet beim Laden: " + fehler0.join(" | "));
if (typeof w0.copilotVerbindung !== "object" || !w0.copilotVerbindung) {
    abbruch("window.copilotVerbindung entsteht nicht – ohne das Modul sind alle "
            + "folgenden Pruefungen trivial wahr");
}
pruefe(!!w0.copilotVerbindung, "window.copilotVerbindung entsteht");
pruefe(typeof w0.t === "function", "window.t (i18n) ist verfuegbar");
pruefe(w0.t("copilot.verbinden") && w0.t("copilot.verbinden") !== "copilot.verbinden",
       "der i18n-Schluessel copilot.verbinden ist belegt: "
       + JSON.stringify(w0.t("copilot.verbinden")));

// ─── 3. Zustaende zeichnen ─────────────────────────────────────────────────
/* Eine Attrappe, die die ECHTE Antwortform liefert: Status + JSON (Register –
 * eine Attrappe mit bequemerer Signatur prueft eine Kette, die es nicht gibt). */
function mitAntworten(w, antworten) {
    const gerufen = [];
    w.fetch = global.fetch = async (pfad, optionen) => {
        gerufen.push({ pfad, methode: (optionen && optionen.method) || "GET" });
        const schluessel = Object.keys(antworten).find((k) => String(pfad).includes(k));
        const a = schluessel ? antworten[schluessel] : { status: 500, daten: {} };
        return {
            status: a.status,
            json: async () => a.daten,
        };
    };
    return gerufen;
}

const STATUS = "/api/copilot/status";

async function zeichnen(w, status) {
    mitAntworten(w, { [STATUS]: { status: 200, daten: status } });
    await w.copilotVerbindung.init();
    return w.document.getElementById("copilot-status-container").innerHTML;
}

(async () => {
    console.log("3. Alles erfuellt, nicht verbunden");
    let html = await zeichnen(w0, {
        eingerichtet: true, verbunden: false, konto: "",
        internet_frei: true, skill_aktiv: true,
    });
    // Positivkontrolle: ohne gezeichnetes Markup ist jede Pruefung trivial.
    if (!html || html.length < 20) {
        abbruch("der Container bleibt leer – es wurde nichts gezeichnet");
    }
    pruefe(html.includes('data-cp-aktion="verbinden"'), "der Verbinden-Knopf ist da");
    pruefe(!/data-cp-aktion="verbinden"[^>]*disabled/.test(html),
           "und er ist bedienbar");
    pruefe(!html.includes("cp-warn"), "kein Vorbedingungs-Hinweis, wenn alles passt");

    console.log("3b. Verbunden");
    html = await zeichnen(w0, {
        eingerichtet: true, verbunden: true, konto: "pruef.nutzer@beispiel.de",
        internet_frei: true, skill_aktiv: true,
    });
    pruefe(html.includes("pruef.nutzer@beispiel.de"), "das Konto wird genannt");
    pruefe(html.includes('data-cp-aktion="trennen"'), "der Trennen-Knopf ist da");
    pruefe(!html.includes('data-cp-aktion="verbinden"'),
           "und KEIN Verbinden-Knopf daneben");
    pruefe(html.includes("Bing") || html.includes("bing"),
           "die Karte sagt, dass die Frage an die Bing-Suche geht");

    console.log("3c. Jede fehlende Vorbedingung nennt ihre Stelle");
    // Je EINE Vorbedingung fehlt – so ist messbar, welcher Hinweis traegt.
    const faelle = [
        ["skill_aktiv", { skill_aktiv: false }, ["Skills"]],
        ["eingerichtet", { eingerichtet: false }, ["Kennung"]],
        ["internet_frei", { internet_frei: false }, ["Berechtigungen"]],
    ];
    for (const [name, abweichung, erwartet] of faelle) {
        const basis = {
            eingerichtet: true, verbunden: false, konto: "",
            internet_frei: true, skill_aktiv: true,
        };
        html = await zeichnen(w0, Object.assign(basis, abweichung));
        pruefe(html.includes("cp-warn"), name + ": ein Hinweis erscheint");
        for (const wort of erwartet) {
            pruefe(html.includes(wort),
                   name + ": der Hinweis nennt die Stelle (" + wort + ")");
        }
    }

    console.log("3d. Ohne Einrichtung oder Freigabe ist der Knopf gesperrt");
    html = await zeichnen(w0, {
        eingerichtet: false, verbunden: false, konto: "",
        internet_frei: true, skill_aktiv: true,
    });
    pruefe(/data-cp-aktion="verbinden"[^>]*disabled/.test(html),
           "ohne Entra-Anwendung ist der Verbinden-Knopf disabled");
    html = await zeichnen(w0, {
        eingerichtet: true, verbunden: false, konto: "",
        internet_frei: false, skill_aktiv: true,
    });
    pruefe(/data-cp-aktion="verbinden"[^>]*disabled/.test(html),
           "ohne Internet-Freigabe ebenso");

    console.log("3e. Die Einrichtungsanleitung steht IM Reiter");
    {
        // Die Scopes kommen aus dem Backend, nicht abgetippt – eine achte
        // Berechtigung dort muss hier ohne Pflege auffallen.
        const quelle = fs.readFileSync(path.join(ROOT, "backend", "copilot_client.py"), "utf8");
        const block = (quelle.match(/\nSCOPES = \(([\s\S]*?)\)/) || [])[1] || "";
        const scopes = (block.match(/"([A-Za-z.]+)"/g) || []).map((x) => x.slice(1, -1));
        if (scopes.length < 7) abbruch("SCOPES aus copilot_client.py nicht lesbar (" + scopes.length + ")");

        const { w } = aufbauen();
        const reiter = w.document.getElementById("settings-tab-copilot");
        const anl = w.document.getElementById("copilot-anleitung");
        pruefe(!!anl && reiter.contains(anl), "die Anleitung liegt im Copilot-Reiter");
        const felder = w.document.getElementById("skcfg-copilot");
        pruefe(!!anl && !!felder
               && (anl.compareDocumentPosition(felder) & w.Node.DOCUMENT_POSITION_FOLLOWING),
               "…und steht VOR den Eingabefeldern");
        const txt = anl ? anl.textContent : "";
        pruefe(txt.includes("Verzeichnis-ID (Mandant)") && txt.includes("Anwendungs-ID (Client)"),
               "sie nennt die Feldnamen, unter denen Entra die Kennungen zeigt");
        pruefe(/ffentliche Clientflows zulassen/.test(txt), "…und den Schalter für die Gerätecode-Anmeldung");
        const fehlt = scopes.filter((sc) => !txt.includes(sc));
        pruefe(fehlt.length === 0, "…und alle Graph-Berechtigungen aus SCOPES", fehlt.join(", "));
        pruefe(!reiter.textContent.includes("docs/copilot"),
               "kein Verweis auf eine Repo-Datei, die der Administrator nicht erreicht");

        // Offen ohne Einrichtung, EINMAL zu mit Einrichtung, danach nicht mehr.
        anl.open = true;
        await zeichnen(w, { eingerichtet: false, verbunden: false, konto: "",
                            internet_frei: true, skill_aktiv: true });
        pruefe(anl.open === true, "ohne Einrichtung bleibt die Anleitung offen");
        const hinweis = w.document.getElementById("copilot-status-container").textContent;
        pruefe(!hinweis.includes("docs/copilot") && hinweis.includes("Entra-Anwendung"),
               "der Hinweis 'Anwendung fehlt' verweist auf den Abschnitt im Reiter");

        const { w: w2 } = aufbauen();
        const anl2 = w2.document.getElementById("copilot-anleitung");
        await zeichnen(w2, { eingerichtet: true, verbunden: false, konto: "",
                             internet_frei: true, skill_aktiv: true });
        pruefe(anl2.open === false, "eingerichtet: die Anleitung ist zugeklappt");
        anl2.open = true;
        await zeichnen(w2, { eingerichtet: true, verbunden: false, konto: "",
                             internet_frei: true, skill_aktiv: true });
        pruefe(anl2.open === true, "…und ein erneutes Zeichnen klappt sie nicht wieder zu");
        // Die folgenden Abschnitte arbeiten wieder auf der ersten Seite.
        global.window = w0;
        global.document = w0.document;
    }

    console.log("4. Ein Ausfall der Auskunft behauptet KEINEN Zustand");
    mitAntworten(w0, { [STATUS]: { status: 500, daten: {} } });
    await w0.copilotVerbindung.init();
    html = w0.document.getElementById("copilot-status-container").innerHTML;
    pruefe(!html.includes('data-cp-aktion="verbinden"'),
           "kein Verbinden-Knopf bei unbekanntem Zustand");
    pruefe(!html.includes('data-cp-aktion="trennen"'),
           "und kein Trennen-Knopf");
    pruefe(html.includes("HTTP 500"), "der Grund nennt den Status");

    console.log("5. Fremdtext wird escaped");
    html = await zeichnen(w0, {
        eingerichtet: true, verbunden: true,
        konto: '<img src=x onerror="alert(1)">',
        internet_frei: true, skill_aktiv: true,
    });
    pruefe(!html.includes("<img"), "ein Tag im Kontonamen landet nicht im Markup");
    pruefe(html.includes("&lt;img"), "er steht escaped da (bleibt lesbar)");
    pruefe(w0.document.querySelectorAll("#copilot-status-container img").length === 0,
           "und es entsteht kein Element daraus");

    console.log("6. Geraete-Anmeldung");
    const START = "/api/copilot/device-start";
    mitAntworten(w0, {
        [STATUS]: { status: 200, daten: {
            eingerichtet: true, verbunden: false, konto: "",
            internet_frei: true, skill_aktiv: true } },
        [START]: { status: 200, daten: {
            user_code: "ABCD-EFGH",
            verification_url: "https://microsoft.com/devicelogin",
            expires_in: 900 } },
    });
    await w0.copilotVerbindung.init();
    await w0.copilotVerbindung.verbinden();
    html = w0.document.getElementById("copilot-status-container").innerHTML;
    pruefe(html.includes("ABCD-EFGH"), "der Code steht in der Karte");
    pruefe(html.includes('class="cp-code"'), "er traegt die Code-Klasse (gross, mono)");
    const link = w0.document.querySelector("#copilot-status-container a.cp-url");
    pruefe(!!link && link.getAttribute("href") === "https://microsoft.com/devicelogin",
           "die Adresse ist verlinkt");
    pruefe(!!link && link.getAttribute("target") === "_blank"
           && /noopener/.test(link.getAttribute("rel") || ""),
           "der Verweis nach aussen traegt target=_blank und rel=noopener");
    pruefe(html.includes('data-cp-aktion="abbrechen"'), "Abbrechen ist moeglich");
    w0.copilotVerbindung.abbrechen();

    console.log("6b. Eine NICHT-https-Adresse wird nicht verlinkt");
    mitAntworten(w0, {
        [STATUS]: { status: 200, daten: {
            eingerichtet: true, verbunden: false, konto: "",
            internet_frei: true, skill_aktiv: true } },
        [START]: { status: 200, daten: {
            user_code: "X", verification_url: "javascript:alert(1)",
            expires_in: 900 } },
    });
    await w0.copilotVerbindung.init();
    await w0.copilotVerbindung.verbinden();
    const boese = w0.document.querySelector("#copilot-status-container a");
    pruefe(!boese, "kein <a> fuer eine javascript:-Adresse");
    pruefe(w0.document.getElementById("copilot-status-container")
             .innerHTML.includes("javascript:alert(1)")
           === true, "die Adresse steht als TEXT da (nicht verschwiegen)");
    w0.copilotVerbindung.abbrechen();

    console.log("7. Der Abhol-Takt wird bei jedem Ende gestoppt");
    // GEZAEHLT wird der Takt, nicht der Quelltext gelesen: ein Timer, der
    // weiterlaeuft, fragt endlos und haelt in jsdom den Prozess offen.
    const ENDEN = [
        ["authorized", { status: "authorized", konto: "a@beispiel.de" }],
        ["expired", { status: "expired", message: "abgelaufen" }],
        ["error", { status: "error", message: "kaputt" }],
        ["idle (Dienst neu gestartet)", { status: "idle" }],
    ];
    for (const [name, antwort] of ENDEN) {
        mitAntworten(w0, {
            [STATUS]: { status: 200, daten: {
                eingerichtet: true, verbunden: false, konto: "",
                internet_frei: true, skill_aktiv: true } },
            [START]: { status: 200, daten: {
                user_code: "C", verification_url: "https://beispiel.de/d",
                expires_in: 900 } },
            "/api/copilot/device-status": { status: 200, daten: antwort },
        });
        await w0.copilotVerbindung.init();
        await w0.copilotVerbindung.verbinden();
        if (!w0.copilotVerbindung._takt) {
            abbruch("nach verbinden() laeuft kein Takt – dann kann dieser "
                    + "Abschnitt sein Stoppen nicht messen");
        }
        await w0.copilotVerbindung._abholen();
        pruefe(!w0.copilotVerbindung._takt, name + ": der Takt ist gestoppt");
        pruefe(w0.copilotVerbindung._laeuft === false,
               name + ": und der Vorgang gilt als beendet");
    }

    console.log("7b. Bei 'pending' laeuft er weiter (Gegenrichtung)");
    mitAntworten(w0, {
        [STATUS]: { status: 200, daten: {
            eingerichtet: true, verbunden: false, konto: "",
            internet_frei: true, skill_aktiv: true } },
        [START]: { status: 200, daten: {
            user_code: "C", verification_url: "https://beispiel.de/d",
            expires_in: 900 } },
        "/api/copilot/device-status": { status: 200, daten: { status: "pending" } },
    });
    await w0.copilotVerbindung.init();
    await w0.copilotVerbindung.verbinden();
    await w0.copilotVerbindung._abholen();
    pruefe(!!w0.copilotVerbindung._takt, "bei pending wird weiter gefragt");
    w0.copilotVerbindung.abbrechen();
    pruefe(!w0.copilotVerbindung._takt, "Abbrechen stoppt ihn");

    console.log("8. Jeder benutzte i18n-Schluessel ist in BEIDEN Sprachen belegt");
    // Ein Schluessel, den nur eine Sprache fuehrt, faellt beim Sprachwechsel
    // STILL aus – der Benutzer sieht dann den Schluesselnamen.
    const benutzt = [...COPILOT_JS.matchAll(/t\('(copilot\.[a-z0-9_]+)'/g)]
        .map((m) => m[1]);
    if (benutzt.length < 10) {
        abbruch("nur " + benutzt.length + " i18n-Schluessel im Modul gefunden – "
                + "die Sonde trifft das Aufrufmuster nicht");
    }
    const einzeln = [...new Set(benutzt)];
    console.log("     " + einzeln.length + " verschiedene Schluessel benutzt");
    for (const k of einzeln) {
        const treffer = (I18N_JS.match(
            new RegExp("'" + k.replace(".", "\\.") + "'\\s*:", "g")) || []).length;
        pruefe(treffer === 2,
               "in DE und EN belegt: " + k + " (" + treffer + "x gefunden)");
    }
    // Und die Markup-Schluessel
    for (const k of ["copilot.reiter_hinweis", "copilot.abschnitt_anwendung",
                     "settings.tab.copilot"]) {
        const treffer = (I18N_JS.match(
            new RegExp("'" + k.replace(/\./g, "\\.") + "'\\s*:", "g")) || []).length;
        pruefe(treffer === 2, "aus dem Markup, in DE und EN: " + k);
    }

    console.log("9. CSS: eigene Klassen sind definiert, keine festen Farben");
    // Eine Klasse ohne jede CSS-Regel faellt niemandem auf (Register:
    // `.ja-actions` war frei erfunden, die Knopfzeile hatte keinen Abstand).
    const cssKlassen = [...COPILOT_JS.matchAll(/class="([^"]*)"/g)]
        .flatMap((m) => m[1].split(/\s+/))
        .filter((c) => c.startsWith("cp-"));
    const einzelnCss = [...new Set(cssKlassen)];
    if (!einzelnCss.length) abbruch("keine cp-Klasse im Modul gefunden");
    for (const c of einzelnCss) {
        // ⚠ NICHT mit `\b` abschliessen: `-` ist ein Nicht-Wort-Zeichen, also
        // liegt zwischen `.cp-code` und `-ungenutzt` eine Wortgrenze – eine
        // umbenannte Regel haette weiter als "definiert" gegolten. Von der
        // Gegenprobe gefunden (Probe 11 blieb stumm): ein Teilstring ist keine
        // Identitaet, dieselbe Klasse wie `share_1` in `share_10` (Register).
        pruefe(new RegExp("\\." + c + "(?![\\w-])").test(STYLE_CSS),
               "in style.css definiert: ." + c);
    }
    // Der Block endet am NAECHSTEN Abschnittskopf (`/* ──`), nicht am
    // Dateiende: bis zum Ende geschnitten zaehlte jeder spaeter angehaengte
    // Block mit (2026-11-07: die rgba(var(--fg-rgb)) des SQL-Assistenten
    // galten als "feste Farbe" des Copilot-Reiters – ein Pruefenster, das in
    // den Nachbarblock greift, Register).
    const _cpAnf = STYLE_CSS.indexOf("Reiter Copilot");
    const _cpEnde = STYLE_CSS.indexOf("\n/* ──", _cpAnf + 1);
    const meinBlock = STYLE_CSS.slice(_cpAnf, _cpEnde > _cpAnf ? _cpEnde : undefined);
    pruefe(meinBlock.length > 200, "der CSS-Block ist auffindbar");
    // Farben nur aus den Variablen – ausgenommen die #000/#fff IN color-mix,
    // das ist der Hausweg fuer lesbare Mischfarben (Register).
    // ⚠ `color-mix\([^)]*\)` GENUEGT NICHT: der Ausdruck enthaelt ein
    // verschachteltes `var(--accent)`, und `[^)]*` endet an DESSEN Klammer –
    // die Mischfarbe blieb damit halb stehen und der Waechter meldete im
    // ersten Lauf ein #fff/#000, das genau an der richtigen Stelle stand.
    // Eine Ebene Verschachtelung muss das Muster also mitnehmen.
    // ⚠ UND ZUERST DIE KOMMENTARE WEG: der Block BEGRUENDET die Kontrastwahl
    // und nennt dabei `#e74c3c` – ohne diesen Schritt liest der Waechter seine
    // eigene Begruendung als Verstoss und meldet eine feste Farbe, die im Code
    // gar nicht steht (so beim ersten Lauf nach der Abnahme passiert).
    // Ersetzt wird durch Leerzeichen GLEICHER Laenge, nicht geloescht – ein
    // Waechter, der den Quelltext umbaut, prueft nicht mehr den Quelltext
    // (Register).
    const ohneKommentar = meinBlock.replace(
        /\/\*[\s\S]*?\*\//g, (m) => " ".repeat(m.length));
    if (/#e74c3c/.test(meinBlock) && /#e74c3c/.test(ohneKommentar)) {
        // Steht die Farbe NACH dem Entfernen noch da, ist sie echter Code.
        console.log("     (Hinweis: #e74c3c steht ausserhalb eines Kommentars)");
    }
    if (ohneKommentar.length !== meinBlock.length) {
        abbruch("der Kommentar-Entferner veraendert die Laenge – dann sind "
                + "die Fundstellen nicht mehr deutbar");
    }
    const ohneMix = ohneKommentar.replace(
        /color-mix\((?:[^()]|\([^()]*\))*\)/g, "MIX");
    // Positivkontrolle der Sonde: wenn nach dem Ersetzen noch ein "color-mix"
    // dasteht, hat sie nicht gegriffen und der Rest ist nicht deutbar.
    if (/color-mix/.test(ohneMix)) {
        abbruch("die color-mix-Sonde greift nicht – der Farbtest waere "
                + "nicht deutbar");
    }
    // Positivkontrolle des Kommentar-Entferners: er MUSS in diesem Block
    // etwas zu tun gehabt haben (der Block ist durchgehend begruendet).
    if (!/\/\*/.test(meinBlock)) {
        abbruch("im CSS-Block steht kein Kommentar – dann ist der Entferner "
                + "unbelegt und der Farbtest nicht deutbar");
    }
    const feste = ohneMix.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(/g) || [];
    pruefe(feste.length === 0,
           "keine festen Farben im Block (gefunden: " + JSON.stringify(feste) + ")");
    pruefe(/body\.light .cp-fehler/.test(STYLE_CSS),
           "--danger als Schrift ist im hellen Thema abgedunkelt (Register)");
    pruefe(/\.cp-knopf\s*\{[^}]*width:\s*auto/.test(STYLE_CSS),
           ".btn-primary traegt width:100% – der Knopf nimmt es zurueck");
    /* Die beiden folgenden Zusagen stammen aus der optischen Abnahme vom
     * 2026-11-06 – jsdom konnte sie nicht finden: es rechnet kein Layout und
     * loest weder color-mix noch die Spezifitaet richtig auf. Gemessen wurde
     * die WIRKUNG in Chrome (3,82 -> 5,74:1 bzw. opacity 1 -> 0.5); hier wird
     * die REGEL festgehalten, damit sie nicht wieder herausfaellt. */
    pruefe(/body\.light\s+\.cp-karte\s+\.kb-btn-danger\s*\{/.test(STYLE_CSS),
           "der Trennen-Knopf ist im hellen Thema abgedunkelt "
           + "(.kb-btn-danger traegt #e74c3c: auf der Karte 3,82:1)");
    pruefe(/\.cp-knopf:disabled\s*\{[^}]*opacity/.test(STYLE_CSS)
           && /\.cp-knopf:disabled\s*\{[^}]*cursor/.test(STYLE_CSS),
           "ein gesperrter Knopf ist SICHTBAR gesperrt (opacity + cursor) – "
           + "sonst sieht er aus wie der bedienbare");

    console.log("10. Keine Emojis als Bedienzeichen");
    // Emojis folgen keinem Theme und fehlen mancherorts ganz (Register).
    const emoji = COPILOT_JS.match(
        /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu) || [];
    pruefe(emoji.length === 0,
           "copilot.js enthaelt kein Emoji (gefunden: " + JSON.stringify(emoji) + ")");

    // ─── Bilanz ────────────────────────────────────────────────────────────
    bilanz = true;
    console.log("\n" + ok + " OK, " + fail + " FAIL");
    dom0.window.close();
    process.exit(fail ? 1 : 0);
})().catch((e) => {
    console.log("ABBRUCH (Exit 2): unerwarteter Fehler: " + (e && e.stack || e));
    process.exit(2);
});
