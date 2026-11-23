#!/usr/bin/env python3
"""Gegenproben zu tests/lib/seite_ausschnitt.js (Waechter test_seite_ausschnitt.js).

Jede Probe nimmt GENAU EINE Zusage des Helfers weg und misst, ob der Waechter
mit Exit 1 UND einer FAIL-Zeile antwortet. Exit 2 oder ein Absturz zaehlen NICHT
als Biss (Register: eine Sabotage, die den Waechter abstuerzen laesst, hat nicht
gebissen).

Sabotiert wird eine KOPIE: Waechter, tests/lib und frontend/settings.html liegen
in einem Wegwerf-Verzeichnis (node_modules als Verweis), der echte Arbeitsbaum
wird nie beschrieben - nach einem kill -9 bleibt dort nichts zurueck, und eine
parallele Aenderung am Helfer kann nicht ueberschrieben werden. Ohne gruenen
Basislauf auf der Kopie ist keine Probe deutbar (Exit 2).
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELFER = "tests/lib/seite_ausschnitt.js"

# (Name, alt, neu) – Ersetzungen in der KOPIE des Helfers
PROBEN = [
    ("Vorfahren fallen weg (Ziel haengt in der Luft)",
     "        for (let e = k.parentNode; e && e !== body; e = e.parentNode) pfad.add(e);\n",
     "        /* kein Pfad */\n"),
    ("das Ziel wird selbst beschnitten",
     "        for (const c of k.childNodes) if (pfad.has(c) && !ziele.has(c)) beschneiden(c);\n",
     "        for (const c of k.childNodes) if (pfad.has(c) || ziele.has(c)) beschneiden(c);\n"),
    ("Geschwister des Pfads bleiben stehen",
     "        k.childNodes = (k.childNodes || []).filter((c) => ziele.has(c) || pfad.has(c));\n",
     "        k.childNodes = (k.childNodes || []).filter((c) => true);\n"),
    ("fehlende ids werden verschwiegen",
     "    return { html: aus, fehlend: [...gesucht].filter((x) => !gefunden.has(x)),\n",
     "    return { html: aus, fehlend: [],\n"),
    ("skripte: true wird ignoriert",
     '            if (opt.skripte && c.tagName === "script") markieren(c);\n',
     ""),
    ("der Kopf faellt weg",
     "    const aus = p5.serialize(doc);\n    return { html: aus, fehlend: [...gesucht]",
     '    _kind(wurzel, "head").childNodes = [];\n    const aus = p5.serialize(doc);\n    return { html: aus, fehlend: [...gesucht]'),
    # ── ohneReiter (die Gegenrichtung)
    ("ohneReiter: der behaltene Reiter faellt mit weg",
     "            if (id !== null && bleibt.has(id)) { gefunden.add(id); return true; }\n",
     "            if (false) { gefunden.add(id); return true; }\n"),
    ("ohneReiter: nichts wird entfernt",
     "            if (!istReiter(c)) return true;\n",
     "            return true;\n"),
    ("ohneReiter: steigt nicht in die Tiefe",
     "        for (const c of k.childNodes) stapel.push(c);\n",
     ""),
    ("ohneReiter: auch Rahmen-Elemente mit id fallen weg",
     '    const istReiter = (k) => _element(k) && /(^|\\s)settings-tab-content(\\s|$)/.test(_attr(k, "class") || "");\n',
     '    const istReiter = (k) => _element(k) && k.tagName === "div" && _attr(k, "id") !== null;\n'),
    ("ohneReiter/huelle: die Option wird ignoriert (Reiter fallen ganz weg)",
     "            if (opt.huelle) { c.childNodes = []; return true; }\n",
     ""),
    ("ohneReiter/huelle: die Huelle behaelt ihren Inhalt",
     "            if (opt.huelle) { c.childNodes = []; return true; }\n",
     "            if (opt.huelle) { return true; }\n"),
    ("mitReitern: kuerzt nie (Reiterseite nicht erkannt)",
     '    const IST_REITERSEITE = /class="[^"]*\\bsettings-tab-content\\b/;\n',
     '    const IST_REITERSEITE = /(?!)/;\n'),
    ("mitReitern: baut doch die volle Seite",
     "            super(h, o);\n",
     "            super(html, o);\n"),
    ("mitReitern: fehlender Reiter laeuft weiter",
     "                        process.exit(2);\n                    }\n                    merker.set(h, A.html);",
     "                    }\n                    merker.set(h, A.html);"),
    ("ohneReiter: fehlende ids werden verschwiegen",
     "    return { html: aus, fehlend: [...bleibt].filter((x) => !gefunden.has(x)), entfernt,\n",
     "    return { html: aus, fehlend: [], entfernt,\n"),
]


def bilanz(text: str):
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def lauf(kopie: Path) -> tuple[int, str]:
    r = subprocess.run(["node", str(kopie / "tests" / "test_seite_ausschnitt.js")],
                       capture_output=True, text=True, cwd=str(kopie), timeout=300)
    return r.returncode, r.stdout + r.stderr


def kopie_anlegen(ziel: Path) -> None:
    (ziel / "tests").mkdir(parents=True)
    (ziel / "frontend").mkdir()
    shutil.copytree(ROOT / "tests" / "lib", ziel / "tests" / "lib",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "tests" / "test_seite_ausschnitt.js", ziel / "tests" / "test_seite_ausschnitt.js")
    shutil.copyfile(ROOT / "frontend" / "settings.html", ziel / "frontend" / "settings.html")
    (ziel / "node_modules").symlink_to(ROOT / "node_modules")


def main() -> int:
    if not (ROOT / "node_modules" / "jsdom").is_dir():
        print("ABBRUCH: node_modules/jsdom fehlt im Repo – die Kopie haette kein jsdom")
        return 2
    kopie = Path(tempfile.mkdtemp(prefix="gegen_seite_ausschnitt_"))
    try:
        kopie_anlegen(kopie)
        helfer = kopie / HELFER
        original = helfer.read_text(encoding="utf-8")

        rc, aus = lauf(kopie)
        b = bilanz(aus)
        if rc != 0 or not b or b[1] != 0:
            print("ABBRUCH: Basislauf auf der Kopie nicht gruen (rc=%s, %s)\n%s" % (rc, b, aus[-800:]))
            return 2
        print("Basislauf gruen (%d OK).\n" % b[0])

        beissen = 0
        for name, alt, neu in PROBEN:
            if original.count(alt) != 1:
                print("  ???  %-50s Anker %dx gefunden" % (name, original.count(alt)))
                continue
            helfer.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                rc, aus = lauf(kopie)
            finally:
                helfer.write_text(original, encoding="utf-8")
            b = bilanz(aus)
            if rc == 1 and b and b[1] > 0:
                beissen += 1
                faelle = [z.strip()[5:60] for z in aus.splitlines() if z.strip().startswith("FAIL")]
                print("  BISS %-50s %d FAIL  %s" % (name, b[1], faelle[:2]))
            elif rc == 0:
                print("  ZAHN %-50s 0 FAIL – beisst NICHT" % name)
            else:
                print("  ABBR %-50s rc=%s ohne gueltige Bilanz – kein Biss\n%s" % (name, rc, aus[-400:]))
        print("\n%d/%d Proben beissen (sabotiert wurde nur die Kopie in %s)" % (beissen, len(PROBEN), kopie))
        return 0 if beissen == len(PROBEN) else 1
    finally:
        shutil.rmtree(kopie, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
