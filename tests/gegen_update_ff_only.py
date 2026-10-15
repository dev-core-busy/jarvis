#!/usr/bin/env python3
"""Gegenprobe zu tests/test_update_ff_only.py: beisst der Waechter?

Jede Probe dreht EINEN Teil zurueck, laesst den Waechter laufen und erwartet
mindestens einen FAIL. Vorher gruener Basislauf, danach Byte-Gleichheit per md5.

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
W = ROOT / "tests" / "test_update_ff_only.py"
UM = ROOT / "backend" / "update_manager.py"

PROBEN = [
    ("Pull ohne --ff-only (Merge)",
     '    rc, out, err = _git(*sig_opt, "pull", "--ff-only", "origin", branch, timeout=60)\n',
     '    rc, out, err = _git(*sig_opt, "pull", "origin", branch, timeout=60)\n'),
    ("Keine Erkennung der abweichenden Historie",
     '                _git("merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD")[0] == 1:\n',
     '                False:\n'),
]


def md5():
    return hashlib.md5(UM.read_bytes()).hexdigest()


def lauf():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(W)], capture_output=True, text=True, env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout


rc, _, aus = lauf()
if rc != 0:
    print("ABBRUCH: Basislauf nicht gruen (rc=%s)\n%s" % (rc, aus[-600:]))
    sys.exit(2)
print("Basislauf gruen")

original = UM.read_bytes()
vorher = md5()
schlecht = 0
try:
    for name, alt, neu in PROBEN:
        text = original.decode("utf-8")
        if text.count(alt) != 1:
            print("ABBRUCH: Probe '%s' – Zeile nicht genau einmal gefunden" % name)
            sys.exit(2)
        UM.write_bytes(text.replace(alt, neu).encode("utf-8"))
        rc, fails, _ = lauf()
        beisst = rc == 1 and fails
        print("  %s %s (%s FAIL)" % ("BEISST" if beisst else "ZAHNLOS", name, fails))
        if not beisst:
            schlecht += 1
        UM.write_bytes(original)
finally:
    UM.write_bytes(original)
if md5() != vorher:
    print("ABBRUCH: update_manager.py nach der Gegenprobe veraendert")
    sys.exit(2)
print("\n%d/%d Proben beissen" % (len(PROBEN) - schlecht, len(PROBEN)))
sys.exit(1 if schlecht else 0)
