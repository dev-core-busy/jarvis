#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_starlette_badhost.py ueberhaupt?

Ein Waechter, der nur beim richtigen Stand gruen ist, beweist nichts – er muss
beim falschen Stand ROT werden. Diese Probe legt dem Waechter gebaute Verstoesse
vor, darunter den echten Ausgangszustand vom 2026-10-01 (``starlette`` ohne
Grenze, ``fastapi==0.115.6``), und verlangt den erwarteten Exit-Code.

Mitgeprueft wird die Teilstring-Falle: ``sse-starlette`` ist NICHT ``starlette``.
Ein Waechter, der das verwechselt, haelt ein Projekt fuer geschuetzt, in dem
Starlette gar nicht deklariert ist.

Erwartung: 0 = Deklaration traegt, 1 = Verstoss erkannt, 2 = konnte nicht laufen.

Lauf:  python3 tests/gegen_starlette_badhost.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WAECHTER = HIER / "test_starlette_badhost.py"
ECHTE_REQ = HIER.parent / "requirements.txt"

GUT_FASTAPI = "fastapi>=0.141.1,<0.142.0"
GUT_STAR = "starlette>=1.0.1"

# (Name, Zeilen der gebauten requirements.txt, erwarteter Exit)
FAELLE = [
    ("Ausgangszustand 2026-10-01: starlette ohne Grenze, fastapi==0.115.6",
     ["fastapi==0.115.6", "uvicorn[standard]==0.34.0", "starlette", "sse-starlette>=3.0.0,<3.1"],
     1),
    ("starlette auf die verwundbare Fassung gepinnt",
     [GUT_FASTAPI, "starlette==0.41.3"],
     1),
    ("starlette-Untergrenze knapp unter dem Fix",
     [GUT_FASTAPI, "starlette>=1.0.0"],
     1),
    ("starlette>1.0.0 (echt groesser) genuegt nicht fuer 1.0.1",
     [GUT_FASTAPI, "starlette>1.0.0"],
     1),
    ("starlette fehlt ganz -> konnte nicht laufen",
     [GUT_FASTAPI, "uvicorn[standard]==0.34.0"],
     2),
    ("Teilstring-Falle: nur sse-starlette da, starlette fehlt",
     [GUT_FASTAPI, "sse-starlette>=3.0.0,<3.1"],
     2),
    ("starlette doppelt deklariert (Absicht unlesbar)",
     [GUT_FASTAPI, GUT_STAR, "starlette>=1.2.0"],
     1),
    ("fastapi zu alt – pinnt starlette<0.42 und macht die Untergrenze unerfuellbar",
     ["fastapi==0.115.6", GUT_STAR],
     1),
    ("fastapi ohne OTel-Obergrenze",
     ["fastapi>=0.141.1", GUT_STAR],
     1),
    ("fastapi ab 0.142 – reisst den OTel-Stack mit",
     ["fastapi>=0.142.2", GUT_STAR],
     1),
    ("Grenze nur im Kommentar, nicht in der Anforderung",
     [GUT_FASTAPI, "starlette  # braucht >=1.0.1 wegen CVE-2026-48710"],
     1),
    ("leere Datei -> konnte nicht laufen",
     [],
     2),
    ("korrekter Stand",
     [GUT_FASTAPI, GUT_STAR, "sse-starlette>=3.0.0,<3.1"],
     0),
]


def lauf(req_pfad):
    p = subprocess.run([sys.executable, str(WAECHTER), str(req_pfad)],
                       capture_output=True, text=True, timeout=60)
    return p.returncode, (p.stdout + p.stderr)


# ── Positivkontrolle: der Waechter muss am ECHTEN Stand gruen sein ───────────
# Ohne grünen Basislauf ist jedes ROT unten nicht deutbar – es koennte auch
# heissen, dass der Waechter immer faellt.
if not WAECHTER.exists():
    print(f"Exit 2: Waechter {WAECHTER} fehlt")
    sys.exit(2)
if not ECHTE_REQ.exists():
    print(f"Exit 2: {ECHTE_REQ} fehlt")
    sys.exit(2)

rc, ausgabe = lauf(ECHTE_REQ)
if rc != 0:
    print(f"Exit 2: Basislauf gegen die echte requirements.txt ist NICHT gruen "
          f"(Exit {rc}). Ohne gruenen Basislauf ist die Gegenprobe nicht deutbar.")
    print(ausgabe[-1500:])
    sys.exit(2)
print(f"  \033[32m✓\033[0m Basislauf gegen echte requirements.txt ist gruen")

# ── Die gebauten Verstoesse ──────────────────────────────────────────────────
beisst = 0
daneben = []

with tempfile.TemporaryDirectory(prefix="gegen-badhost-") as tmp:
    for i, (name, zeilen, erwartet) in enumerate(FAELLE):
        pfad = Path(tmp) / f"requirements-{i}.txt"
        pfad.write_text("\n".join(zeilen) + ("\n" if zeilen else ""), encoding="utf-8")
        rc, ausgabe = lauf(pfad)
        if rc == erwartet:
            beisst += 1
            print(f"  \033[32m✓\033[0m Exit {rc} (erwartet {erwartet}) – {name}")
        else:
            daneben.append((name, erwartet, rc, ausgabe))
            print(f"  \033[31m✗\033[0m Exit {rc}, ERWARTET {erwartet} – {name}")

print(f"\n{'─' * 60}")
if daneben:
    print(f"FAIL: {len(daneben)} von {len(FAELLE)} Faellen falsch bewertet – "
          f"der Waechter misst nicht, was er zu messen behauptet.\n")
    for name, erwartet, rc, ausgabe in daneben:
        print(f"── {name}\n   erwartet Exit {erwartet}, war Exit {rc}")
        print("   " + "\n   ".join(ausgabe.strip().splitlines()[-8:]) + "\n")
    sys.exit(1)

print(f"OK: alle {len(FAELLE)} Faelle richtig bewertet – der Waechter beisst.")
sys.exit(0)
