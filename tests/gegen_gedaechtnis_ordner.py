#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_gedaechtnis_ordner.py`` (Pentest F-14).

Jede Probe nimmt GENAU EINE Zusage weg und misst, ob der Waechter sie meldet:
Exit 1, eine Bilanzzeile, und die GEMEINTE FAIL-Zeile ist dabei.

Wie ``gegen_google_geheimnisse.py``: es wird KEINE Datei gepatcht. Sabotiert
wird im Speicher – das Modul wird vorab geladen, sein Quelltext mit genau EINER
Ersetzung (Zaehlpruefung, sonst PROBE-ABBRUCH) in den Modul-Namensraum
zurueckgefuehrt, und der Waechter laeuft per ``runpy`` im selben Prozess. Nach
einem ``kill -9`` bleibt damit kein Rueckstand im Arbeitsbaum.

Bewusst OHNE Probe: die Startreihenfolge in main.py (Abschnitt 6) – der
Waechter liest dort die DATEI, eine Sabotage im Speicher erreicht sie nicht.
Exit 0 = alle beissen, 1 = mindestens eine stumm, 2 = Basis nicht gruen.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_gedaechtnis_ordner.py"

# (Name, Modul, alt, neu, erwartete FAIL-Zeile)
PROBEN = [
    ("Pfad wieder direkt in data/", "backend.tools.memory",
     'return gedaechtnis_dir() / f"memory_', 'return _DATA_DIR / f"memory_',
     "Pfad je Benutzer liegt in data/gedaechtnis"),
    ("Konflikt ueberschreibt das Ziel", "backend.tools.memory",
     'ziel = ziel_dir / f"{p.name}.vor-umzug-{marke}"', "pass",
     "Konflikt: das Ziel (neuer Code) gewinnt"),
    ("Ordner-Modus wird nicht nachgezogen", "backend.tools.memory",
     "os.chmod(d, GEDAECHTNIS_MODUS)", "pass",
     "Ordner ist 0750"),
    ("Datei vor dem Verschieben nicht privat", "backend.tools.memory",
     "privat_machen(p)          # vor dem replace", "pass  # vor dem replace",
     "umgezogene Dateien sind nicht fremd lesbar"),
    ("Rueckweg beim Laden fehlt", "backend.tools.memory",
     "            umziehen()\n        _ordner_bereit()",
     "            pass\n        _ordner_bereit()",
     "Altbestand wird beim Laden gefunden"),
    ("Umzug unter _lock (Selbstblockade)", "backend.tools.memory",
     "with _umzug_lock:", "with _lock:",
     "Laden unter _lock blockiert nicht"),
    ("Namen in der Rueckgabe", "backend.tools.memory",
     '    erg = {"verschoben": 0, "doppelt": 0, "konflikt": 0, "fehler": []}\n',
     '    erg = {"verschoben": 0, "doppelt": 0, "konflikt": 0, "fehler": []}\n'
     '    erg["fehler"] = [p.name for p in _DATA_DIR.glob("memory_*")]\n',
     "Rueckgabe traegt keine Namen"),
    ("PRIVATE_DIRS ohne Ordner", "backend.sandbox",
     '                "data/gedaechtnis",\n', "",
     "PRIVATE_DIRS fuehrt data/gedaechtnis"),
    ("_APP_DENY_REL ohne Ordner", "backend.sandbox",
     '    "data/gedaechtnis",\n    # ⚠ `data/generated_images`',
     '    # ⚠ `data/generated_images`',
     "is_sensitive: Datei im Ordner ist geschuetzt"),
    ("Shell-Sperre ohne Ordner", "backend.sandbox",
     "    r'/gedaechtnis\\b|'\n", "",
     "Shell-Sperre trifft den Ordner"),
    ("Zusammenfuehrung sucht am alten Ort", "backend.benutzer_migration",
     'Ablage("memory", DATA / "gedaechtnis",', 'Ablage("memory", DATA,',
     "Benutzer-Zusammenfuehrung sucht im Ordner"),
    ("Wissens-Aufraeumen sucht am alten Ort", "backend.wissen_aufraeumen",
     'sorted((DATA / "gedaechtnis").glob("memory_*.json"))', "[]",
     "Wissens-Aufraeumen findet Gedaechtnisse im Ordner"),
]

VORLADER = '''
import importlib, runpy, sys, types
sys.path.insert(0, {root!r})
_cfg = types.ModuleType("backend.config")
class _C:
    def get_setting(self, k, d=None): return d
    def get(self, k, d=None): return d
    def get_skill_states(self): return {{}}
_cfg.config = _C()
sys.modules["backend.config"] = _cfg
mod = importlib.import_module({modul!r})
src = open(mod.__file__, encoding="utf-8").read()
n = src.count({alt!r})
if n != 1:
    print("PROBE-ABBRUCH: Anker %d-mal gefunden statt einmal" % n)
    sys.exit(2)
exec(compile(src.replace({alt!r}, {neu!r}), mod.__file__, "exec"), mod.__dict__)
sys.argv = [{waechter!r}]
runpy.run_path({waechter!r}, run_name="__main__")
'''


def lauf(modul, alt, neu) -> tuple[int, str]:
    code = VORLADER.format(root=str(ROOT), modul=modul, alt=alt, neu=neu,
                           waechter=str(WAECHTER))
    p = subprocess.run([sys.executable, "-"], input=code, text=True,
                       capture_output=True, cwd=str(ROOT), timeout=300,
                       env={"PYTHONDONTWRITEBYTECODE": "1",
                            "PATH": "/usr/bin:/bin", "HOME": str(Path.home())})
    return p.returncode, p.stdout + p.stderr


def bilanz(text: str):
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


print("Basislauf: der Waechter ist ohne Sabotage gruen")
r0 = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                    text=True, cwd=str(ROOT), timeout=300)
b0 = bilanz(r0.stdout + r0.stderr)
if b0 is None or b0[1] or r0.returncode != 0:
    print(f"ABBRUCH: Basis nicht gruen ({b0}, exit {r0.returncode}) – "
          "ohne gruene Basis ist keine Gegenprobe deutbar")
    sys.exit(2)
print(f"  + {b0[0]} OK, 0 FAIL, exit 0")

print("\nProben")
beissen, stumm = 0, []
for name, modul, alt, neu, erwartet in PROBEN:
    rc, text = lauf(modul, alt, neu)
    b = bilanz(text)
    if "PROBE-ABBRUCH" in text or b is None:
        grund = next((z for z in text.splitlines() if "PROBE-ABBRUCH" in z),
                     "keine Bilanzzeile")
        print(f"  ! {name}: Probe unbrauchbar – {grund}")
        stumm.append(name + " (unbrauchbar)")
        continue
    gemeint = any(z.strip().startswith("FAIL") and erwartet in z
                  for z in text.splitlines())
    if rc == 1 and b[1] > 0 and gemeint:
        beissen += 1
        print(f"  + {name}: {b[1]} FAIL, gemeinte Zeile dabei")
    else:
        stumm.append(name)
        print(f"  - {name}: exit {rc}, {b[1]} FAIL, gemeinte Zeile dabei: {gemeint}")

print(f"\n{beissen} von {len(PROBEN)} Proben beissen")
if stumm:
    print("STUMM: " + ", ".join(stumm))
sys.exit(1 if stumm else 0)
