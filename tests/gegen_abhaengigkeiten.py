#!/usr/bin/env python3
"""Gegenprobe zu tests/test_abhaengigkeiten.py: beisst der Waechter?

Jede Probe dreht EINE Regel in backend/abhaengigkeiten.py zurueck und erwartet
mindestens einen FAIL. Gruener Basislauf vorher, Byte-Gleichheit danach, ohne Bytecode.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_abhaengigkeiten.py"
M = "backend/abhaengigkeiten.py"

PROBEN = [
    ("Pakete ueber der Grenze werden herabgestuft (alles als zu_alt)", M,
     '        (erg["zu_neu"] if zu_neu else erg["zu_alt"]).append(rq)\n',
     '        erg["zu_alt"].append(rq)\n'),
    ("ueber-Grenze-Paket nicht festgehalten", M,
     '    zeilen += [f"{r.name}=={inst[_norm(r.name)]}" for r in e["zu_neu"]]\n', ''),
    ("transitive Pakete duerfen sinken (bcrypt-Fall)", M,
     '        zeilen.append(f"{n}=={v}" if "+" in v else f"{n}>={v}")\n', '        pass\n'),
    ("Ausnahmen werden gehoben", M,
     '        if f["ausgenommen"] or not f["behoben_in"] or f["paket"] in NIE_HEBEN:\n',
     '        if not f["behoben_in"] or f["paket"] in NIE_HEBEN:\n'),
    ("torch/pip nicht geschuetzt", M,
     'NIE_HEBEN = {"torch", "pip", "setuptools", "wheel"}\n', 'NIE_HEBEN = set()\n'),
    ("groesste statt kleinste Behebung je Fund", M,
     '    return min(kandidaten) if kandidaten else None\n',
     '    return max(kandidaten) if kandidaten else None\n'),
    ("Vorabversionen als Behebung", M,
     '                    if fv > v_inst and not fv.is_prerelease:\n',
     '                    if fv > v_inst:\n'),
    ("abgelaufene Ausnahmen gelten weiter", M,
     '                if dt.date.fromisoformat(m.group(2)) >= heute:\n', '                if True:\n'),
    ("keine Ruecknahme bei gescheitertem Import-Test", M,
     '            erg["zurueckgesetzt"] = _zuruecksetzen(vorher, nachher)\n',
     '            erg["zurueckgesetzt"] = []\n'),
    ("nur-pruefen installiert trotzdem", M,
     '    if installieren and (fehl or ziele):\n', '    if fehl or ziele:\n'),
    ("ohne Constraints installiert", M,
     '            r = _pip("install", "-c", cf.name, *basis, *hebungen)\n',
     '            r = _pip("install", *basis, *hebungen)\n'),
    # ── Lock-Modus ──
    ("Lock-Modus ohne Schalter an (Vorgabe 'an')", M,
     '    return os.environ.get("JARVIS_ABH_LOCK", "0") == "1" and LOCK.is_file()\n',
     '    return os.environ.get("JARVIS_ABH_LOCK", "1") == "1" and LOCK.is_file()\n'),
    ("Lock-Modus ohne Lock-Datei", M,
     '    return os.environ.get("JARVIS_ABH_LOCK", "0") == "1" and LOCK.is_file()\n',
     '    return os.environ.get("JARVIS_ABH_LOCK", "0") == "1"\n'),
    ("Lock ohne --require-hashes installiert", M,
     '        r = _pip("install", "--require-hashes", "-Ccompile-args=-j2",\n',
     '        r = _pip("install", "-Ccompile-args=-j2",\n'),
    ("Lock-Modus stuft nicht herab (nur fehlend/aelter)", M,
     '    return [(n, inst.get(n), v) for n, v in sorted(soll.items()) if inst.get(n) != v]\n',
     '    return [(n, inst.get(n), v) for n, v in sorted(soll.items())\n'
     '            if inst.get(n) is None or Version(inst[n]) < Version(v)]\n'),
    ("Ruecknahme im Lock-Modus ohne torch", M,
     '            erg["zurueckgesetzt"] = _zuruecksetzen(vorher, nachher, geschuetzt=NIE_HEBEN - {"torch"})\n',
     '            erg["zurueckgesetzt"] = _zuruecksetzen(vorher, nachher)\n'),
    ("Ruecknahme ohne CPU-Index fuer +cpu", M,
     '        extra = ["--extra-index-url", TORCH_INDEX] if any("+" in a for a in alt) else []\n',
     '        extra = []\n'),
    ("Lock-Modus nur pruefen installiert trotzdem", M,
     '    if installieren and ab:\n', '    if ab:\n'),
    ("Absturz im Import-Test ohne Modulnamen (leerer Grund)", M,
     '    if r.returncode < 0 or r.returncode > 128:\n', '    if False:\n'),
    ("Lock-Lauf kehrt vor _speichern zurueck", M,
     '            _lock_lauf(erg, vorher, installieren)\n        else:\n',
     '            _lock_lauf(erg, vorher, installieren)\n            return erg\n        else:\n'),
]
DATEIEN = [M, "tests/test_abhaengigkeiten.py"]


def md5(p):
    return hashlib.md5((ROOT / p).read_bytes()).hexdigest()


def lauf():
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def main():
    sich = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}
    f, rc = lauf()
    if f != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (f, rc))
        return 2
    print("Basislauf gruen.\n")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            p = ROOT / datei
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, t.count(alt)))
                continue
            p.write_text(t.replace(alt, neu), encoding="utf-8")
            try:
                f, rc = lauf()
            finally:
                p.write_bytes(sich[datei])
            if f > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, f))
            elif f < 0:
                print("  ABBR %-58s rc=%s" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, b in sich.items():
            (ROOT / d).write_bytes(b)
    if {d: md5(d) for d in DATEIEN} != vorher:
        print("ABBRUCH: Dateien nicht byte-gleich")
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
