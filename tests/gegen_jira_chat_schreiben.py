#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_jira_chat_schreiben.py?

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis, uebergeben ueber JS_AGENT /
JS_WIRKUNG – die echten Dateien werden nie angefasst. Vorher ein gruener
Basislauf; eine Probe "beisst" nur mit Exit 1 UND mindestens einem FAIL
(Exit 2 oder fehlende Bilanzzeile zaehlen nicht).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = [sys.executable, str(HIER / "test_jira_chat_schreiben.py")]
DATEIEN = {
    "agent": (ROOT / "backend" / "agent.py", "JS_AGENT"),
    "wirkung": (ROOT / "backend" / "wirkung.py", "JS_WIRKUNG"),
}

_SCHLEIFE = ("        for tool in self._tool_instances:\n"
             "            self.tools_map[tool.name] = tool\n")
_SCHLEIFE_ALT = ("        for tool in self._tool_instances:\n"
                 "            if tool.name in _JIRA_SCHREIB_TOOLS:\n"
                 "                continue\n"
                 "            self.tools_map[tool.name] = tool\n")

# (Name, Datei, alt, neu)
PROBEN = [
    ("Altstand: __init__ filtert die Schreibwerkzeuge aus tools_map", "agent",
     "        self.tools_map: dict[str, object] = {}\n" + _SCHLEIFE,
     "        self.tools_map: dict[str, object] = {}\n" + _SCHLEIFE_ALT),
    ("Altstand: reload_skills filtert die Schreibwerkzeuge aus tools_map", "agent",
     "        self.tools_map.clear()\n" + _SCHLEIFE,
     "        self.tools_map.clear()\n" + _SCHLEIFE_ALT),
    ("Angebot ohne Jira-Bedingung", "agent",
     "            if name in _JIRA_SCHREIB_TOOLS and not jira_schreiben:\n"
     "                continue\n", ""),
    ("Praedikat immer wahr (gemeinsamer Zugang bekommt das Angebot)", "agent",
     '            return z.get("quelle") == jira_accounts.QUELLE_PERSOENLICH\n',
     "            return True\n"),
    ("Praedikat fail-closed bei nicht lesbarer Aufloesung", "agent",
     '– Angebot unveraendert",\n                  flush=True)\n            return True\n',
     '– Angebot unveraendert",\n                  flush=True)\n            return False\n'),
    ("Praedikat fragt ohne Benutzer", "agent",
     'jira_accounts.aufloesen(self.actor_name() or "")', "jira_accounts.aufloesen()"),
    ("Prompt-Absatz ohne Praedikat", "agent",
     "            _jira_schreibt = (any(n in self.tools_map for n in _JIRA_SCHREIB_TOOLS)\n"
     "                              and self._jira_schreiben_moeglich())\n",
     "            _jira_schreibt = any(n in self.tools_map for n in _JIRA_SCHREIB_TOOLS)\n"),
    ("alter Satz 'bewusst deaktiviert' wieder unbedingt", "agent",
     '"präzise Suchbegriffe, fasse die Treffer zusammen und nenne Titel/Key und Link."\n',
     '"präzise Suchbegriffe, fasse die Treffer zusammen und nenne Titel/Key und Link. "\n'
     '                "Du darfst dort NICHTS anlegen, ändern oder löschen – schreibende '
     'Aktionen sind bewusst deaktiviert."\n'),
    ("jira_add_comment ohne Bestaetigung", "wirkung",
     '    "jira_add_comment": AUSSEN,\n', ""),
    ("Schreibmenge um ein Werkzeug zu klein", "agent",
     '_JIRA_SCHREIB_TOOLS = frozenset({"jira_create_issue", "jira_add_comment"})',
     '_JIRA_SCHREIB_TOOLS = frozenset({"jira_create_issue"})'),
]


def lauf(umgebung: dict) -> tuple:
    """(Exit, FAIL-Zahl oder None ohne Bilanzzeile, Ausgabe)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    r = subprocess.run(WAECHTER, cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout + r.stderr


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
    print("Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_jira_chat_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??     {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
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
                print("         " + aus.strip().splitlines()[-1][:200] if aus.strip() else "")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
