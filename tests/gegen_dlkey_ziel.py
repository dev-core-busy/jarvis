#!/usr/bin/env python3
"""Gegenproben zu Pentest F-20 (Abruf-Schluessel je Adresse, 2026-11-17).

Jede Probe nimmt GENAU EINE Zusage weg und misst, ob der zugehoerige Waechter
mit Exit 1 UND der gemeinten FAIL-Zeile meldet. Ein Waechter, der auch ohne den
Fix gruen bleibt, ist kein Beweis (Register).

Zwei Arten von Proben:
  * PYTHON (``download_key``): Sabotage im SPEICHER – das Modul wird vorab
    geladen, veraendert und der Waechter per ``runpy`` im selben Prozess
    ausgefuehrt. Nach einem ``kill -9`` bleibt nichts im Arbeitsbaum.
  * JS (``dlkey.js``): der Waechter liest die Datei selbst, also wird sie
    GEPATCHT – vorher gesichert, danach zurueckgelegt und per md5 geprueft;
    ein Rueckstand aus einem abgebrochenen Lauf wird beim Start erkannt.
Ohne gruenen Basislauf ist keine Probe deutbar (Exit 2).
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_W = ROOT / "tests" / "test_download_key.py"
JS_W = ROOT / "tests" / "test_dlkey_ablauf.js"
DLKEY = ROOT / "frontend" / "js" / "dlkey.js"
SICHERUNG = ROOT / "tests" / ".gegen_dlkey_ziel.sicherung"
UMG = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# (Name, Sabotage-Code im Speicher, gemeinte FAIL-Zeile)
PY_PROBEN = [
    ("Ziel wird nicht verglichen (alle Ziele gleicher Hash)",
     "dk.ziel_hash = lambda kanon: 'x' * 24",
     "fuer eine ANDERE Datei abgewiesen"),
    ("Cache-Buster t zaehlt doch zum Ziel",
     "dk._ZIEL_OHNE = ('token',)",
     "token und der Cache-Buster t zaehlen nicht zum Ziel"),
    ("Parameter werden nicht sortiert",
     "import urllib.parse as _up\n"
     "def _kanon(pfad, params):\n"
     "    p = _up.unquote(str(pfad or ''))\n"
     "    paare = [(str(k), str(v)) for k, v in (params or ()) if str(k) not in dk._ZIEL_OHNE]\n"
     "    return p + ('?' + _up.urlencode(paare) if paare else '')\n"
     "dk.ziel_kanon = _kanon",
     "Reihenfolge und Kodierung der Parameter sind gleichgueltig"),
    ("Pruefung ohne Ziel laesst durch (fail-open)",
     "_pv = dk.pruefen_voll\n"
     "def _offen(s, ziel=None):\n"
     "    if not ziel and dk.ist_abrufschluessel(s or ''):\n"
     "        t = (s or '').split('.')\n"
     "        return (dk._unb64(t[1]), t[3] != 'v', None) if len(t) == 7 else (None, True, None)\n"
     "    return _pv(s, ziel)\n"
     "dk.pruefen_voll = _offen",
     "OHNE Ziel gibt es keinen Zugang"),
]

VORLADER = '''
import runpy, sys, types
sys.path.insert(0, {root!r})
_cfg = types.ModuleType("backend.config")
class _C:
    SECRET_KEY = "testgeheimnis-fuer-den-waechter"
    def get_setting(self, k, d=None):
        return {{"download_key_ttl_min": 15}}.get(k, d)
_cfg.config = _C()
sys.modules["backend.config"] = _cfg
from backend import download_key as dk
_vorher = (dk.ziel_hash, dk._ZIEL_OHNE, dk.ziel_kanon, dk.pruefen_voll)
{sabotage}
if (dk.ziel_hash, dk._ZIEL_OHNE, dk.ziel_kanon, dk.pruefen_voll) == _vorher:
    print("PROBE-ABBRUCH: Sabotage hat nichts veraendert"); sys.exit(2)
sys.argv = [{waechter!r}]
runpy.run_path({waechter!r}, run_name="__main__")
'''

# (Name, alt, neu, gemeinte FAIL-Zeile) – Ersetzungen in dlkey.js
JS_PROBEN = [
    ("EIN Schluessel fuer alle Adressen (Zustand vor F-20)",
     [("        var k = merk(u);\n        if (!k) return null;\n        var e = lager().keys[k];",
       "        var k = merk(u) && '/';\n        if (!k) return null;\n        var e = lager().keys[k];"),
      ("                    if (k && e && e.key) l.keys[k] = { key: e.key, exp: e.exp };",
       "                    if (k && e && e.key) l.keys['/'] = { key: e.key, exp: e.exp };")],
     # Mit EINEM gemeinsamen Eintrag gewinnt der zuletzt gespeicherte (der des
     # Bildes) – es scheitert also der LINK, nicht das Bild.
     "der Link traegt danach SEINEN Schluessel"),
    ("kein Sammelabruf (eine Adresse je Abruf)",
     [("        var namen = Object.keys(_offen).slice(0, MAX_ZIELE);",
       "        var namen = Object.keys(_offen).slice(0, 1);")],
     "GENAU EIN Abruf fuer beide Adressen"),
    ("Nachziehen ins DOM faellt aus",
     [("                lagerSchreiben(l);\n                aktualisiere();",
       "                lagerSchreiben(l);")],
     "der Link traegt danach SEINEN Schluessel"),
    ("Cache-Buster t ist Teil des Merkschluessels",
     [("            q.delete('token'); q.delete('t');", "            q.delete('token');")],
     "ein anderer Cache-Buster t braucht keinen neuen Schluessel"),
]


def bilanz(text: str):
    m = re.search(r"(\d+)\s*(?:OK|ok)[, /]+\s*(\d+)\s*FAIL", text) or re.search(
        r"Ergebnis: (\d+)/(\d+)", text)
    if not m:
        return None
    if "/" in m.group(0):
        gut, ges = int(m.group(1)), int(m.group(2))
        return gut, ges - gut
    return int(m.group(1)), int(m.group(2))


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def zurueck():
    if SICHERUNG.exists():
        shutil.copyfile(SICHERUNG, DLKEY)
        SICHERUNG.unlink()


if SICHERUNG.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – dlkey.js wird zurueckgelegt.")
    zurueck()

print("\033[1mBasislauf\033[0m")
basis_ok = True
for w, cmd in ((PY_W, [sys.executable, str(PY_W)]), (JS_W, ["node", str(JS_W)])):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=600, env=UMG)
    b = bilanz(r.stdout + r.stderr)
    print(f"  {w.name}: exit {r.returncode}, Bilanz {b}")
    if b is None or b[1] or r.returncode != 0:
        basis_ok = False
if not basis_ok:
    print("ABBRUCH: Basis ist NICHT gruen – ohne gruene Basis ist keine Gegenprobe deutbar")
    sys.exit(2)

beissen, stumm = 0, []


def werte(name, rc, text, gemeint):
    global beissen
    b = bilanz(text)
    if "PROBE-ABBRUCH" in text or b is None:
        stumm.append(name + " (unbrauchbar)")
        print(f"  ! {name}: Probe unbrauchbar – {text.strip()[-200:]}")
        return
    treffer = any(("FAIL" in z or "✗" in z) and gemeint in z for z in text.splitlines())
    if rc == 1 and b[1] > 0 and treffer:
        beissen += 1
        print(f"  + {name}: {b[1]} FAIL, gemeinte Zeile dabei")
    else:
        stumm.append(name)
        print(f"  - {name}: exit {rc}, {b[1]} FAIL, gemeinte Zeile dabei: {treffer}")


print("\n\033[1mPython-Proben (download_key, im Speicher)\033[0m")
for name, sab, gemeint in PY_PROBEN:
    code = VORLADER.format(root=str(ROOT), sabotage=sab, waechter=str(PY_W))
    r = subprocess.run([sys.executable, "-"], input=code, text=True, capture_output=True,
                       cwd=str(ROOT), timeout=600, env=UMG)
    werte(name, r.returncode, r.stdout + r.stderr, gemeint)

print("\n\033[1mJS-Proben (dlkey.js, gepatcht)\033[0m")
original = md5(DLKEY)
try:
    for name, ersetzungen, gemeint in JS_PROBEN:
        shutil.copyfile(DLKEY, SICHERUNG)
        try:
            text = DLKEY.read_text(encoding="utf-8")
            for alt, neu in ersetzungen:
                if text.count(alt) != 1:
                    raise RuntimeError(f"Anker trifft nicht ({text.count(alt)}x): {alt[:60]!r}")
                text = text.replace(alt, neu)
            DLKEY.write_text(text, encoding="utf-8")
            r = subprocess.run(["node", str(JS_W)], capture_output=True, text=True,
                               cwd=str(ROOT), timeout=600, env=UMG)
            werte(name, r.returncode, r.stdout + r.stderr, gemeint)
        except RuntimeError as e:
            stumm.append(name + " (Anker)")
            print(f"  ! {name}: {e}")
        finally:
            zurueck()
finally:
    zurueck()
if md5(DLKEY) != original:
    print("ABBRUCH: dlkey.js ist nach den Proben NICHT byte-gleich – bitte pruefen!")
    sys.exit(2)

gesamt = len(PY_PROBEN) + len(JS_PROBEN)
print(f"\n{beissen} von {gesamt} Proben beissen; dlkey.js byte-gleich wiederhergestellt")
if stumm:
    print("STUMM: " + ", ".join(stumm))
sys.exit(1 if stumm else 0)
