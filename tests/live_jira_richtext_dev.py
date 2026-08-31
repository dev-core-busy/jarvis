#!/usr/bin/env python3
"""Live-Probe auf DEV zum Rich-Text-Ergebnisfeld der Jira-Erweiterung.

Laeuft IM Produktiv-venv auf dem Server, gegen den DEPLOYTEN Code.

Zwei Teile, und der zweite ist der Grund fuer diese Datei:
  1. Das Paket beider Varianten wird WIRKLICH gebaut und hineingesehen – nur so
     faellt auf, wenn der Branding-Schritt das Feld zerlegt oder eine Datei
     fehlt.
  2. Der ECHTE Parser aus dem deployten popup.js laeuft gegen einen ECHTEN
     Modelltext. Mit `--ticket` wird dafuer ein Ticket ausgewertet und das Fett
     ueber den Zusatzwunsch ERZWUNGEN – ohne das liefert das Modell auf DEV
     gar keines (0 von 14 gemessenen Laeufen), und die Probe wuerde eine
     Funktion pruefen, die im Lauf nicht auftritt.

Ausgegeben werden nur Kennzahlen, nie Ticketinhalte.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, "/opt/jarvis")

_ok = _fail = 0


def check(text, bed, extra=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (" - " + str(extra) if extra else ""))


from backend import jira_assist as ja           # noqa: E402

ADDON = "/opt/jarvis/browser-addon"

print("\n═══ 1) Das gebaute Paket traegt das Rich-Text-Feld")
for variante in ("chrome", "firefox"):
    name, daten = ja.paket_bauen(variante, basis="https://dev.test")
    z = zipfile.ZipFile(io.BytesIO(daten))
    html = z.read("popup.html").decode("utf-8")
    js = z.read("popup.js").decode("utf-8")
    css = z.read("popup.css").decode("utf-8")
    ein = z.read("einfuegen.js").decode("utf-8")
    p = variante + ": "
    check(p + "das Feld ist contenteditable",
          'id="f-ergebnis"' in html and 'contenteditable="true"' in html)
    check(p + "und keine textarea mehr", '<textarea id="f-ergebnis"' not in html)
    # Der Branding-Schritt schreibt in popup.html – er darf das Feld nicht
    # anfassen.
    check(p + "der Branding-Schritt laesst Rolle und Platzhalter stehen",
          'role="textbox"' in html and "data-platzhalter" in html)
    check(p + "die Feld-Funktionen sind im Paket",
          "function textZuFeld(" in js and "function feldZuText(" in js)
    check(p + "einfuegen.js nimmt die geparste Struktur entgegen",
          "function einfuegenInJira(text, bloecke)" in ein)
    # Ohne Deckel schoebe eine lange Antwort den Einfuegen-Knopf aus dem
    # 600-px-Fenster.
    check(p + "der Hoehendeckel ist im Paket", "max-height" in css)
    check(p + "keine Datei fehlt",
          set(ja.PAKET_DATEIEN).issubset(set(z.namelist())))


print("\n═══ 2) Der ECHTE Parser gegen einen ECHTEN Modelltext")
key = ""
for i, a in enumerate(sys.argv):
    if a == "--ticket" and i + 1 < len(sys.argv):
        key = sys.argv[i + 1]
if not key:
    print("  (uebersprungen – ohne --ticket ABC-123 gibt es keinen echten Text)")
else:
    d = asyncio.run(ja.auswerten(
        key, modus="zusammenfassung", lang="de", user="jarvis",
        hinweis="Hebe die Abschnittsbeschriftungen mit **doppelten "
                "Sternchen** hervor."))
    text = d.get("text") or ""
    print("  Antwort: %d Zeichen" % len(text))

    js = open(os.path.join(ADDON, "popup.js"), encoding="utf-8").read()

    def schneide(name):
        m = re.search(r"(?:async )?function %s\([^)]*\)\s*\{[\s\S]*?\n\}" % name, js)
        return m.group(0) if m else ""

    # DOM-frei: jsdom gibt es auf dem Server nicht. Geprueft wird die
    # Kern-Eigenschaft des Parsers; die DOM-Haelfte misst der Waechter
    # (tests/test_browser_addon.js, Abschnitt 15).
    skript = (re.search(r"const _FETT_RE = .*;", js).group(0) + "\n"
              + schneide("zuBloecken") + "\n" + schneide("hatFett") + "\n"
              + schneide("ohneFett") + r"""
const text = JSON.parse(process.argv[2]);
const b = zuBloecken(text);
const zurueck = b.map(z => z.map(l => l.fett ? "**" + l.t + "**" : l.t).join(""))
                 .join("\n");
console.log(JSON.stringify({
  zeilen: b.length,
  fettlaeufe: b.reduce((n, z) => n + z.filter(l => l.fett).length, 0),
  hatFett: hatFett(b),
  verlustfrei: zurueck === text,
  ohne_sternchen: ohneFett(text).indexOf("**") < 0,
  gleiche_zeilenzahl:
    ohneFett(text).split("\n").length === text.split("\n").length,
}));
""")
    with tempfile.NamedTemporaryFile("w", suffix=".js", dir="/tmp",
                                     delete=False) as f:
        f.write(skript)
        pfad = f.name
    try:
        r = subprocess.run(["node", pfad, json.dumps(text)],
                           capture_output=True, text=True)
        if r.returncode:
            check("der Parser laeuft gegen den echten Text", False,
                  r.stderr[:200])
        else:
            v = json.loads(r.stdout)
            print("  %d Zeilen, %d Fettlaeufe" % (v["zeilen"], v["fettlaeufe"]))
            check("das Modell hat Fett geliefert", v["fettlaeufe"] > 0,
                  "ohne Fett beweist der Rest nichts")
            check("die Struktur meldet Fett", v["hatFett"])
            check("Laeufe -> Text ist VERLUSTFREI", v["verlustfrei"])
            check("der bereinigte Text traegt keine Sternchen",
                  v["ohne_sternchen"])
            check("und hat dieselbe Zeilenzahl", v["gleiche_zeilenzahl"])
    finally:
        os.unlink(pfad)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
