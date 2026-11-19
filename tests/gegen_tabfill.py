#!/usr/bin/env python3
"""Gegenprobe zu tests/test_tabfill_ui.js, Teil 4 ("JarvisTabfill.vorschlag")
und Teil 5 (die Regel ueber alle placeholder-Zuweisungen).

Jede Probe dreht EINE Zusage zurueck (Ersetzung ganzer Zeilen), laesst den
Waechter laufen und erwartet mindestens einen FAIL (Exit 1). Exit 2 zaehlt
NICHT als Biss – dann hat die Positivkontrolle der Messvorrichtung
abgebrochen, und der Lauf ist von "nicht gelaufen" nicht zu unterscheiden.
Vorher gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5.

Sabotiert wird ausschliesslich das PRODUKT, nie der Waechter selbst: eine
Probe, die die Regel aus dem Waechter entfernt, misst nichts (Register).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_tabfill_ui.js"
SICHERUNG = Path.home() / ".gegen_tabfill_sicherung"

TF = "frontend/js/tabfill.js"
IDP = "frontend/js/settings_idp.js"
AIM = "frontend/js/ai_mouse_admin.js"
LK = "frontend/js/loeschkonzept.js"
KBS = "frontend/js/knowledge_sync.js"
MCP = "frontend/js/mcp.js"
SAP = "frontend/sap.html"
EMAIL = "frontend/email.html"
CRON = "frontend/js/cron.js"

PROBEN = [
    # ── Teil 4: die zentrale Funktion ──
    ("zentrale Funktion nicht ausgestellt", TF,
     "    window.JarvisTabfill = { vorschlag: vorschlagSetzen };\n", ""),
    # Die ZEILE wird ersetzt, nicht entfernt: ohne das `if` stuende das `else`
    # darunter allein, und der Waechter stuerbe an einem SyntaxError statt zu
    # beissen (Register: eine Sabotage, die abstuerzen laesst, hat nicht gebissen).
    ("Vorschlag ohne Markierung (der gemeldete Fehler)", TF,
     "        if (s) el.setAttribute('data-tabfill', '');\n",
     "        if (false) el.setAttribute('data-tabfill', '');\n"),
    ("leerer Vorschlag raeumt die Markierung nicht ab", TF,
     "        else el.removeAttribute('data-tabfill');\n", ""),
    ("Attribut traegt eine Kopie statt des Platzhalters", TF,
     "        if (s) el.setAttribute('data-tabfill', '');\n",
     "        if (s) el.setAttribute('data-tabfill', s);\n"),
    ("Platzhalter gar nicht gesetzt", TF,
     "        el.placeholder = s;\n", ""),

    # ── Teil 5: die Regel, je Fundstelle einzeln ──
    ("Rueckkehr-Adresse wieder roh (der gemeldete Fall)", IDP,
     "            JarvisTabfill.vorschlag(ru, d.redirect_uri_vorschlag);\n",
     "            ru.placeholder = d.redirect_uri_vorschlag || '';\n"),
    ("Zeitstempeldienst wieder roh", AIM,
     "                JarvisTabfill.vorschlag(tsa, d.tsa_standard || 'http://timestamp.digicert.com');\n",
     "                tsa.placeholder = d.tsa_standard || 'http://timestamp.digicert.com';\n"),
    ("Key-Vault-Anmeldung wieder roh", AIM,
     "            if (auth) { JarvisTabfill.vorschlag(auth, kv.anmeldung_standard); }\n",
     "            if (auth && kv.anmeldung_standard) { auth.placeholder = kv.anmeldung_standard; }\n"),
    ("Aufbewahrungsfrist wieder roh", LK,
     "        JarvisTabfill.vorschlag(inp, String(f.vorgabe));\n",
     "        inp.placeholder = String(f.vorgabe);\n"),
    ("Standortname wieder roh", KBS,
     "                    JarvisTabfill.vorschlag(site, r.data.hostname);\n",
     "                    site.placeholder = r.data.hostname;\n"),

    # ── Teil 5: eine Ausnahme verliert ihre Begruendung ──
    # Der Anker nimmt die Folgezeile mit: die Marke steht in dieser Datei
    # dreimal (key/ca/env), ein Anker ueber die Marke allein traefe alle drei.
    ("Ausnahme ohne Marke (neue Stelle faellt durch)", MCP,
     "                    // tabfill: nein – 'leer lassen = unveraendert', kein Wert\n"
     "                    $('[data-f=\"key\"]').placeholder = _tt('mcp.key_keep_ph',",
     "                    $('[data-f=\"key\"]').placeholder = _tt('mcp.key_keep_ph',"),

    # ── Teil 1b: Ablehnung, Kennwort, Beispiel-Vorsatz (2026-11-19) ──
    ("Ablehnung wird ignoriert", TF,
     "        if (el.hasAttribute('data-tabfill-nein')) return false;\n", ""),
    ("Kennwortfeld nimmt den Vorschlag", TF,
     "        if ((el.getAttribute('type') || '').toLowerCase() === 'password') return false;\n", ""),
    ("'z. B.' bleibt im Feld stehen", TF,
     "        var t = (s || '').trim().replace(BEISPIEL_VORSATZ, '').trim();\n",
     "        var t = (s || '').trim();\n"),

    # ── Teil 6: das Markup (der zweite gemeldete Fall) ──
    ("Basis-URL wieder ohne Markierung (gemeldet)", SAP,
     '<input data-tabfill class="sp-input" id="sp-acc-od-url"',
     '<input class="sp-input" id="sp-acc-od-url"'),
    ("Formvorgabe verliert ihre Ablehnung", EMAIL,
     ' data-tabfill-nein="Formmuster mit Platzhalterteilen – uebernommen waere es falsch" type="email" id="em-adresse"',
     ' type="email" id="em-adresse"'),

    # ── Teil 7: von einem Modul erzeugtes Feld ──
    ("erzeugtes Feld ohne Entscheidung", CRON,
     ' data-tabfill-nein="Beispielnummer – keine echte Rufnummer" id="watcher-wa-to"',
     ' id="watcher-wa-to"'),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf() -> tuple[int, str]:
    r = subprocess.run(["node", str(WAECHTER)], cwd=ROOT, capture_output=True,
                       text=True, timeout=300)
    zeile = next((z for z in reversed(r.stdout.splitlines())
                  if "FAIL" in z or z.strip().startswith("ABBRUCH")), "")
    return r.returncode, zeile.strip()


def zurueck() -> None:
    if not SICHERUNG.exists():
        return
    for rel in DATEIEN:
        quelle = SICHERUNG / rel
        if quelle.exists():
            shutil.copy2(quelle, ROOT / rel)
    shutil.rmtree(SICHERUNG)


def main() -> int:
    # Regel statt gepflegter Liste: jede angefasste Datei wird auch gesichert.
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Dateiliste unvollstaendig.")
        return 2
    zurueck()  # Rueckstand eines abgebrochenen Laufs
    # Trefferkontrolle VOR dem Basislauf: ein Anker, der nicht trifft, macht
    # aus einer stummen Probe faelschlich einen "zahnlosen Waechter".
    for name, rel, alt, _neu in PROBEN:
        n = (ROOT / rel).read_text(encoding="utf-8").count(alt)
        if n != 1:
            print("ABBRUCH: Anker %dx gefunden – %s" % (n, name))
            return 2
    code, zeile = lauf()
    if code != 0:
        print("ABBRUCH: Basislauf nicht gruen (%s, Exit %d)" % (zeile, code))
        return 2
    print("Basislauf gruen: " + zeile)
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    SICHERUNG.mkdir(mode=0o700)
    for rel in DATEIEN:
        (SICHERUNG / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, SICHERUNG / rel)
    stumm = []
    try:
        for name, rel, alt, neu in PROBEN:
            pfad = ROOT / rel
            original = pfad.read_text(encoding="utf-8")
            pfad.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                code, zeile = lauf()
            finally:
                pfad.write_text(original, encoding="utf-8")
            biss = code == 1
            print("%s  %-48s %s (Exit %d)"
                  % ("BEISST" if biss else "STUMM ", name, zeile, code))
            if not biss:
                stumm.append(name)
    finally:
        zurueck()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("FEHLER: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print("\nDateien byte-gleich wiederhergestellt.")
    print("Bilanz: %d von %d Proben beissen" % (len(PROBEN) - len(stumm), len(PROBEN)))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
