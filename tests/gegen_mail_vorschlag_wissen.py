#!/usr/bin/env python3
"""Gegenprobe: beissen tests/test_mail_vorschlag_wissen.py und
tests/test_mail_vorschlag_wissen_ui.js? (Wissensdatenbank beim Antwortvorschlag)

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis (WV_RUNNER / ADDIN_JS) – die
echten Dateien werden nie angefasst. Vorher ein gruener Basislauf; eine Probe
"beisst" nur mit Exit 1 UND mindestens einem FAIL (Exit 2 und Abstuerze zaehlen
nicht).

Nicht als Probe enthalten, weil verhaltensgleich: "der Haken zaehlt jedes
Werkzeug". Im Zuschnitt liegt nur die Wissenssuche, und die harte Schranke
sitzt VOR dem Haken – ein anderes Werkzeug erreicht ihn nie.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = [
    [sys.executable, str(HIER / "test_mail_vorschlag_wissen.py")],
    ["node", str(HIER / "test_mail_vorschlag_wissen_ui.js")],
]
DATEIEN = {
    "runner": (ROOT / "backend" / "mail_runner.py", "WV_RUNNER"),
    "addin": (ROOT / "frontend" / "addin" / "addin.js", "ADDIN_JS"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Sendewerkzeug im Zuschnitt", "runner",
     "        return {WISSEN_WERKZEUG}\n",
     "        return {WISSEN_WERKZEUG, \"email_senden\"}\n"),
    ("Freigabe wird nicht beachtet", "runner",
     "    if \"wissen\" in frei:\n", "    if True:\n"),
    ("voll heisst keine Schranke", "runner",
     "    if \"wissen\" in frei:\n",
     "    if \"voll\" in frei:\n        return None\n    if \"wissen\" in frei:\n"),
    ("Konfigurationsfehler oeffnet", "runner",
     "        frei = []                       # fail-closed: keine Werkzeuge\n",
     "        frei = [\"wissen\"]\n"),
    ("Zuschnitt wird nicht gesetzt", "runner",
     "        _agent._role_tools = set(werkzeuge)\n", "        _agent._role_tools = None\n"),
    ("Regel-Zuschnitt statt eigenem", "runner",
     "    werkzeuge = vorschlag_werkzeuge()\n",
     "    werkzeuge = mail_rules.werkzeuge_fuer(mail_rules.freigegebene_bereiche()) or set()\n"),
    ("Wissensabschnitt auch ohne Freigabe", "runner",
     "        + (_VORSCHLAG_WISSEN if werkzeuge else \"\")\n", "        + _VORSCHLAG_WISSEN\n"),
    ("Haken bleibt am geteilten Agenten haengen", "runner",
     "            _agent._schritt_hook = hook_vorher\n", ""),
    ("Haken zaehlt nichts", "runner",
     "            genutzt.append(name) if name == WISSEN_WERKZEUG else None)\n",
     "            None)\n"),
    ("Rueckmeldung behauptet Wissen immer", "runner",
     "        \"wissen\": bool(werkzeuge), \"wissen_suchen\": len(genutzt),\n",
     "        \"wissen\": True, \"wissen_suchen\": len(genutzt),\n"),
    ("Add-in zeigt die Zeile nie", "addin",
     "            if (_vorschlag.wissen) {\n", "            if (false) {\n"),
    ("Add-in zeigt die Zeile auch ohne Freigabe", "addin",
     "            if (_vorschlag.wissen) {\n", "            if (true) {\n"),
    ("Add-in verschweigt die Zahl", "addin",
     "                    _vorschlag.wissen_suchen > 0\n", "                    false\n"),
]


def lauf(umgebung: dict) -> tuple:
    """Alle Pruefstaende; Rueckgabe (Exit, FAIL-Summe, Ausgabe).

    Exit 2 bei irgendeinem Pruefstand geht vor (konnte nicht messen); eine
    fehlende Bilanzzeile heisst FAIL None – das zaehlt nicht als Biss."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    codes, summe, aus = [], 0, ""
    for befehl in WAECHTER:
        r = subprocess.run(befehl, cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
        codes.append(r.returncode)
        aus += r.stdout + r.stderr
        if m is None:
            summe = None
        elif summe is not None:
            summe += int(m.group(2))
    code = 2 if 2 in codes else max(codes)
    return code, summe, aus


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print(f"Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_vorschlag_wissen_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??  {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, aus = lauf({var: str(ziel)})
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL)")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
