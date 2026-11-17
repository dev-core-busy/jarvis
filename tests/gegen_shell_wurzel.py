#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_shell_wurzel.py`` (Pentest F-13/F-16/F-19).

Jede Probe nimmt GENAU EINE Zusage weg und misst, ob der Waechter das meldet –
mit Exit 1 UND der gemeinten FAIL-Zeile. Sabotiert wird im SPEICHER (Vorbild
``gegen_google_geheimnisse.py``): die Module werden vorab importiert, veraendert
und der Waechter per ``runpy`` im selben Prozess ausgefuehrt. Nach einem
``kill -9`` bleibt damit kein Rueckstand im Arbeitsbaum.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_shell_wurzel.py"

# (Name, Sabotage-Code, erwartete FAIL-Zeile)
PROBEN = [
    ("F-15: data/cve faellt aus PRIVATE_DIRS",
     "sb.PRIVATE_DIRS = tuple(x for x in sb.PRIVATE_DIRS if x != 'data/cve')",
     "data/cve danach 0750"),
    ("F-02: Muster fuer Anweisungs-Verzeichnisse entfaellt",
     "sb.PRIVATE_DIR_GLOBS = ()",
     "data/instructions-safe-20260804-191216 danach 0750"),
    ("F-02: Muster folgt Symlinks",
     "import pathlib as _pl\n"
     "_isl = _pl.Path.is_symlink\n"
     "_pl.Path.is_symlink = lambda self: False",
     "Verweis-Ziel bleibt unberuehrt"),
    ("F-18: Dateiwerkzeug sperrt die Wissensverwaltung nicht",
     "sb.wissen_intern = lambda rp: False",
     "Dateiwerkzeug: Entwurf gesperrt"),
    ("F-18: Gruppen-Sicherung (.bak) faellt durch",
     "_w = sb.wissen_intern\n"
     "sb.wissen_intern = lambda rp: _w(rp) and not str(rp).endswith('.bak')",
     "Gruppen-Sicherung gesperrt"),
    ("F-18: harte Sperre statt weicher (Kontosperre droht)",
     "_s = sb.is_sensitive\n"
     "sb.is_sensitive = lambda rp: _s(rp) or sb.wissen_intern(rp)",
     "WEICHE Sperre"),
    ("F-18: Shell verdeckt die Entwuerfe nicht",
     "lt.WISSEN_VERDECKT = ()\n"
     "_a = lt.minimal_wurzel\n"
     "def _ohne_verd():\n"
     "    lt.WISSEN_VERDECKT = ()\n"
     "    return _a()\n"
     "lt.minimal_wurzel = _ohne_verd",
     "Entwurfs-Ordner ist im Lauf leer"),
    ("F-18: Suchindex faellt aus PRIVATE_DIRS",
     "sb.PRIVATE_DIRS = tuple(x for x in sb.PRIVATE_DIRS if x != 'data/vector_store')",
     "Suchindex-Ordner danach 0750"),
    ("F-18: Gruppenkonfiguration faellt aus PRIVATE_FILES",
     "sb.PRIVATE_FILES = tuple(x for x in sb.PRIVATE_FILES if 'groups' not in x)",
     ".groups.json danach 0640"),
    ("Zustand vor dem Fix: --dev-bind / /",
     "lt.minimal_wurzel = lambda: ['--dev-bind', '/', '/']",
     "Projektbaum im Lauf NICHT VORHANDEN"),
    ("Wurzel bindet den Projektbaum mit ein",
     "_a = lt.minimal_wurzel\n"
     "lt.minimal_wurzel = lambda: _a() + ['--ro-bind', str(lt.PROJECT_ROOT), str(lt.PROJECT_ROOT)]",
     "der Projektbaum wird NICHT eingebunden"),
    ("Wissensorte laufen auseinander (/mnt/jarvis-kb fehlt)",
     "lt.WISSEN_ORTE = tuple(w for w in lt.WISSEN_ORTE if w != '/mnt/jarvis-kb')",
     "dieselbe Menge"),
    ("data/documents als Wissensort der Shell",
     "lt.WISSEN_ORTE = lt.WISSEN_ORTE + (str(sb.DOCS_ROOT),)",
     "data/documents ist KEIN Wissensort"),
    ("/etc-Verdeckung entfaellt",
     "lt.ETC_VERBORGEN = ()",
     "im Lauf verdeckt"),
    ("Geraeteknoten fehlen",
     "_a = lt.minimal_wurzel\n"
     "def _ohne_dev():\n"
     "    l = _a(); i = l.index('--dev')\n"
     "    return l[:i] + l[i + 2:]\n"
     "lt.minimal_wurzel = _ohne_dev",
     "frische Geraeteknoten"),
    ("F-16: .git faellt aus PRIVATE_DIRS",
     "sb.PRIVATE_DIRS = tuple(x for x in sb.PRIVATE_DIRS if x != '.git')",
     ".git steht in PRIVATE_DIRS"),
    ("Wissensort wird beschreibbar eingebunden",
     "_a = lt.minimal_wurzel\n"
     "def _rw():\n"
     "    l = _a()\n"
     "    return ['--bind' if t == '--ro-bind' and i + 1 < len(l) and l[i + 1] in lt.WISSEN_ORTE"
     " else t for i, t in enumerate(l)]\n"
     "lt.minimal_wurzel = _rw",
     "NICHT beschreibbar"),
]

VORLADER = '''
import runpy, sys
sys.path.insert(0, {root!r})
import backend.lauf_tmp as lt
import backend.sandbox as sb
_zust = lambda: (repr(lt.minimal_wurzel()), lt.WISSEN_ORTE, lt.ETC_VERBORGEN, sb.PRIVATE_DIRS,
                 sb.PRIVATE_FILES, lt.WISSEN_VERDECKT, sb.wissen_intern, sb.is_sensitive,
                 sb.PRIVATE_DIR_GLOBS, __import__('pathlib').Path.is_symlink)
vorher = _zust()
{sabotage}
nachher = _zust()
if nachher == vorher:
    print("PROBE-ABBRUCH: Sabotage hat nichts veraendert")
    sys.exit(2)
sys.argv = [{waechter!r}]
runpy.run_path({waechter!r}, run_name="__main__")
'''


def lauf(sabotage: str) -> tuple[int, str]:
    code = VORLADER.format(root=str(ROOT), sabotage=sabotage, waechter=str(WAECHTER))
    p = subprocess.run([sys.executable, "-"], input=code, text=True,
                       capture_output=True, cwd=str(ROOT), timeout=600,
                       env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return p.returncode, p.stdout + p.stderr


def bilanz(text: str):
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


print("\033[1mBasislauf: der Waechter ist ohne Sabotage gruen\033[0m")
r0 = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                    text=True, cwd=str(ROOT), timeout=600)
b0 = bilanz(r0.stdout + r0.stderr)
if b0 is None:
    print("ABBRUCH: keine Bilanzzeile im Basislauf")
    sys.exit(2)
if b0[1] or r0.returncode != 0:
    print(f"ABBRUCH: Basis ist NICHT gruen ({b0[0]} OK, {b0[1]} FAIL, exit {r0.returncode})"
          " – ohne gruene Basis ist keine Gegenprobe deutbar")
    sys.exit(2)
print(f"  + {b0[0]} OK, 0 FAIL, exit 0")

print("\n\033[1mProben\033[0m")
beissen, stumm = 0, []
for name, sabotage, erwartet in PROBEN:
    rc, text = lauf(sabotage)
    b = bilanz(text)
    if "PROBE-ABBRUCH" in text or b is None:
        grund = next((z for z in text.splitlines() if "PROBE-ABBRUCH" in z or "ABBRUCH" in z),
                     "keine Bilanzzeile: " + text.strip()[-200:])
        print(f"  ! {name}: Probe unbrauchbar – {grund}")
        stumm.append(name + " (unbrauchbar)")
        continue
    gemeint = any(z.strip().startswith("FAIL") and erwartet in z for z in text.splitlines())
    if rc == 1 and b[1] > 0 and gemeint:
        beissen += 1
        print(f"  + {name}: {b[1]} FAIL, exit 1, gemeinte Zeile dabei")
    else:
        stumm.append(name)
        print(f"  - {name}: exit {rc}, {b[1]} FAIL, gemeinte Zeile dabei: {gemeint}")

print(f"\n{beissen} von {len(PROBEN)} Proben beissen")
if stumm:
    print("STUMM: " + ", ".join(stumm))
sys.exit(1 if stumm else 0)
