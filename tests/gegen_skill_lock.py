#!/usr/bin/env python3
"""Gegenprobe zu tests/test_skill_lock.py: beisst der Waechter?

Jede Probe verfaelscht die Skill-Lock oder das Manifest an EINER Stelle und
erwartet mindestens einen FAIL. Gruener Basislauf vorher, Byte-Gleichheit danach.
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
WAECHTER = ROOT / "tests" / "test_skill_lock.py"
L = "skills/ai_mouse/requirements.lock"
M = "skills/ai_mouse/skill.json"


def _zeile(muster):
    """Die EINE Zeile der Lock, die mit `muster` beginnt (fuer stabile Anker)."""
    t = (ROOT / L).read_text(encoding="utf-8")
    treffer = [z for z in t.splitlines(keepends=True) if z.startswith(muster)]
    return treffer[0] if len(treffer) == 1 else "\0kein-eindeutiger-anker\0"


def _block(muster):
    """Eintrag `muster` samt ALLEN seinen Hash-Zeilen (ein Rad je Plattform –
    nur die erste zu entfernen liesse den Eintrag gehasht, Probe stumm)."""
    t = (ROOT / L).read_text(encoding="utf-8")
    m = re.search(r"^" + re.escape(muster) + r"[^\n]*\n(?:    --hash=sha256:[0-9a-f]{64}[^\n]*\n)+",
                  t, re.M)
    return m.group(0) if m else "\0kein-anker\0"


PROBEN = [
    ("Eintrag ohne Hash (spacy)", L,
     lambda: _block("spacy==3.8.18"),
     lambda: "spacy==3.8.18\n"),
    ("andere spacy-Version in der Lock", L,
     lambda: _zeile("spacy==3.8.18"), lambda: _zeile("spacy==3.8.18").replace("3.8.18", "3.8.17")),
    ("Kernpaket abweichend von requirements.lock (numpy)", L,
     lambda: _zeile("numpy=="), lambda: re.sub(r"==\S+", "==1.26.4", _zeile("numpy=="), count=1)),
    ("Modell-Hash vertauscht", L,
     lambda: "    --hash=sha256:b903f592", lambda: "    --hash=sha256:0003f592"),
    ("Manifest bekommt eine Abhaengigkeit, die die Lock nicht kennt", M,
     lambda: '    "opencv-python-headless==4.13.0.92"\n',
     lambda: '    "opencv-python-headless==4.13.0.92",\n    "tldextract==1.0.0"\n'),
    ("Kopf ohne Erzeuger", L,
     lambda: "--skill ai_mouse – NICHT", lambda: "– NICHT"),
]
DATEIEN = [L, M, "tests/test_skill_lock.py"]


def md5(p):
    return hashlib.md5((ROOT / p).read_bytes()).hexdigest()


def lauf():
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def main():
    fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlt:
        print("ABBRUCH: Proben fassen ungesicherte Dateien an: %s" % sorted(fehlt))
        return 2
    sich = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}
    f, rc = lauf()
    if f != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (f, rc))
        return 2
    print("Basislauf gruen.\n")
    beissen = 0
    try:
        for name, datei, alt_f, neu_f in PROBEN:
            p = ROOT / datei
            t = p.read_text(encoding="utf-8")
            alt, neu = alt_f(), neu_f()
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
                print("  BISS %-62s %d FAIL" % (name, f))
            elif f < 0:
                print("  ABBR %-62s rc=%s" % (name, rc))
            else:
                print("  ZAHN %-62s 0 FAIL – beisst NICHT" % name)
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
