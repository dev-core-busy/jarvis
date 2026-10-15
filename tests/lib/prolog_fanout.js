/* Startet die beobachteten Pruefstaende fuer `test_prolog_vollstaendig.js` -
 * mit begrenzter Gleichzeitigkeit statt seriell.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT. Der Waechter ist ein SAMMELLAUF IM SAMMELLAUF:
 * er startet jeden der ~86 Pruefstaende als eigenen Prozess. Seriell ist seine
 * Laufzeit die SUMME der anderen und waechst mit jedem neuen Pruefstand - in
 * der CI gemessen 286,6 s / 300,1 s / 305,3 s bei einem Deckel von 300 s, also
 * zweimal gerissen (2026-10-11). Der eigene Zeitdeckel in ci_lauf.py hat das
 * entschaerft; das hier nimmt die Ursache.
 *
 * ⚠ WARUM EINE EIGENE DATEI UND KEINE ZEICHENKETTE IM WAECHTER. Ein in eine
 * andere Datei eingebettetes Node-Skript ist nicht diagnostizierbar: am
 * 2026-10-11 lautete ein Abbruchgrund woertlich "node lieferte nichts
 * Lesbares:  s/loader:1613:10)", und die Ursache liess sich nur finden, indem
 * man das Skript aus der Wirtsdatei herausloest und von Hand startet. Als
 * eigene Datei ist sie lesbar, pruefbar und einzeln startbar.
 *
 * ⚠ DIE REIHENFOLGE DER AUSWERTUNG BLEIBT SERIELL. Hier werden nur Prozesse
 * gestartet; jeder schreibt seine eigene .jsonl. Der Waechter liest sie
 * danach in DATEIREIHENFOLGE - sonst wandert seine Ausgabe von Lauf zu Lauf,
 * und eine Bilanz, die sich bei gleichem Code aendert, ist keine Messung.
 *
 * Gleichzeitigkeit: dieselbe Grenze, die ci_lauf.py aussen fuer genau diese
 * Dateien schon benutzt (--parallel 4). Sie laufen dort also heute bereits
 * nebenlaeufig - diese Datei fuegt keine neue Konfliktklasse hinzu. Bewusst
 * KEINE hohe Zahl: der Waechter ist selbst einer der parallelen Plaetze des
 * aeusseren Laufs, die Gleichzeitigkeit multipliziert sich.
 *
 * Aufruf (vom Waechter, nicht von Hand noetig):
 *   node tests/lib/prolog_fanout.js <auftrag.json>
 * Auftrag: { "wurzel": "...", "ablage": "...", "namen": [...],
 *            "grenze": 4, "zeitdeckel_ms": 300000 }
 * Ausgabe: je Pruefstand eine Zeile "<name>\t<rc>\t<signal>" auf stdout -
 * der Waechter braucht sie nicht, aber ohne sie ist ein haengender Starter
 * von einem langsamen nicht zu unterscheiden.
 * Exit 0 = alle gestartet und beendet · 2 = Auftrag unbrauchbar
 */
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const auftragDatei = process.argv[2];
if (!auftragDatei) {
    console.error("ABBRUCH: kein Auftrag uebergeben");
    process.exit(2);
}
let A;
try {
    A = JSON.parse(fs.readFileSync(auftragDatei, "utf8"));
} catch (e) {
    console.error("ABBRUCH: Auftrag nicht lesbar: " + e.message);
    process.exit(2);
}
for (const feld of ["wurzel", "ablage", "namen"]) {
    if (!A[feld]) { console.error("ABBRUCH: Feld fehlt: " + feld); process.exit(2); }
}
if (!Array.isArray(A.namen) || !A.namen.length) {
    console.error("ABBRUCH: keine Namen im Auftrag");
    process.exit(2);
}
const GRENZE = Math.max(1, A.grenze || 4);
const DECKEL = A.zeitdeckel_ms || 300000;

/* Ein Pruefstand. Das Ergebnis interessiert hier NICHT inhaltlich - der
 * Waechter liest die .jsonl. Gemeldet wird nur, dass der Prozess zu einem
 * Ende kam; ein eigener Deckel verhindert, dass ein haengender Pruefstand
 * den ganzen Starter aufhaelt. */
function einer(name) {
    return new Promise((fertig) => {
        const ziel = path.join(A.ablage, name + ".jsonl");
        const kind = spawn(process.execPath, [path.join("tests", name)], {
            cwd: A.wurzel,
            stdio: "ignore",
            env: Object.assign({}, process.env, { PROLOG_PRUEFUNG: ziel }),
        });
        let erledigt = false;
        const uhr = setTimeout(() => {
            if (!erledigt) { try { kind.kill("SIGKILL"); } catch (e) { } }
        }, DECKEL);
        const ende = (rc, sig) => {
            if (erledigt) return;
            erledigt = true;
            clearTimeout(uhr);
            process.stdout.write(name + "\t" + (rc === null ? "-" : rc) + "\t" + (sig || "-") + "\n");
            fertig();
        };
        kind.on("exit", ende);
        // Startet der Prozess gar nicht (ENOENT, EAGAIN), kommt KEIN "exit" -
        // ohne diesen Zweig wartet der Starter bis zum Deckel.
        kind.on("error", (e) => ende(null, "start:" + e.code));
    });
}

(async () => {
    const warteschlange = A.namen.slice();
    const arbeiter = Array.from({ length: Math.min(GRENZE, warteschlange.length) },
        async () => {
            for (;;) {
                const name = warteschlange.shift();
                if (name === undefined) return;
                await einer(name);
            }
        });
    await Promise.all(arbeiter);
    process.exit(0);
})();
