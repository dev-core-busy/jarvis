#!/usr/bin/env python3
"""Gegenproben zu ``test_wissensgraph_unveraendert.py``.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter sie
meldet (Exit 1 mit FAIL-Zeilen UND Bilanz – ein Abbruch ist kein Biss).
Mechanik wie ``gegen_wissensgraph_nachlauf_last.py``: Sicherung auf Platte,
Laufmarke nimmt den Rueckstand eines abgeschossenen Laufs beim naechsten Start
zurueck, gruener Basislauf ist Bedingung, jede angefasste Datei steht geprueft
in DATEIEN, gelaufen wird ohne Bytecode.

    python3 tests/gegen_wissensgraph_unveraendert.py
"""
from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-wg-unveraendert"
MARKE = ABL / "LAUF"

WG = "backend/wissensgraph.py"
WGX = "backend/wissensgraph_extraktion.py"
DATEIEN = [WG, WGX]
WAECHTER = [sys.executable, str(ROOT / "tests" / "test_wissensgraph_unveraendert.py")]
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

PROBEN = [
    ("Arbeiter extrahiert auch bei gleichem Text", WGX,
     '    if not eintrag.get("voll"):\n        alt = await',
     '    if False:\n        alt = await'),
    ("Arbeiter ignoriert den Neuaufbau mit voll", WGX,
     '    if not eintrag.get("voll"):\n        alt = await',
     '    if True:\n        alt = await'),
    ("Pruefsumme der Extraktion ohne kopf_entfernen", WGX,
     "    text = eingabe_text(chunks)\n    teile = bloecke(",
     "    text = text_aus_chunks(chunks)\n    teile = bloecke("),
    ("Loesungsarchiv-Kopf wird nicht erkannt", WGX,
     "    m = _LOESUNGSARCHIV_KOPF.search(text[:800])\n",
     "    m = None\n"),
    ("Ticketliste bleibt stehen", WGX,
     '        return _LOESUNGSARCHIV_TICKETS.sub("", rest).strip()\n',
     "        return rest.strip()\n"),
    ("Ticketliste frisst auch Inhalt dahinter", WGX,
     'r"(?: · gelöst \\d{4}-\\d{2}-\\d{2})?)*\\s*$")',
     'r"(?: · gelöst \\d{4}-\\d{2}-\\d{2})?)*.*$")'),
    ("Abgleich reicht voll nicht weiter", WGX,
     "wg.einreihen(m, mtime, sichern=False, voll=voll)",
     "wg.einreihen(m, mtime, sichern=False)"),
    ("Bestaetigen setzt den Inhaltsstand auf die neue mtime", WG,
     '        q["stand"] = stand_von(q)\n',
     '        q["stand"] = float(mtime)\n'),
    ("Bestaetigen markiert den Graphen als veraltet", WG,
     '        q["bestaetigt"] = time.time()\n',
     '        q["bestaetigt"] = time.time()\n        _veraltet_markieren()\n'),
    ("inhalts_stand liefert wieder die mtime", WG,
     "    return _indizes()[1]\n",
     "    return _indizes()[0]\n"),
    ("Widerspruchs-Gueltigkeit wieder ueber die mtime", WG,
     "    return _widersprueche_gueltig(inhalts_stand())",
     "    return _widersprueche_gueltig(quellen_index())"),
    ("Graph-Ableitung prueft Befunde wieder gegen die mtime", WG,
     '    stand = {q["pfad"]: stand_von(q) for q in quellen}\n',
     '    stand = {q["pfad"]: float(q.get("mtime") or 0) for q in quellen}\n'),
    ("Frische Extraktion setzt keinen stand", WG,
     '"mtime": float(mtime), "stand": float(mtime), "modell": modell,',
     '"mtime": float(mtime), "modell": modell,'),
    ("Erneutes Einreihen mit gleicher mtime merkt voll nicht", WG,
     '            if voll and not alt.get("voll"):\n',
     "            if False:\n"),
]



def _ablage(rel: str) -> Path:
    return ABL / rel.replace("/", "__")


def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, _ablage(rel))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        if _ablage(rel).is_file():
            shutil.copy2(_ablage(rel), ROOT / rel)


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


def lauf() -> tuple[int, str]:
    p = subprocess.run(WAECHTER, cwd=ROOT, capture_output=True, text=True, timeout=300, env=UMG)
    return p.returncode, p.stdout + p.stderr


def bewerte() -> tuple[bool, str]:
    rc, aus = lauf()
    bil = [z for z in aus.splitlines() if z.startswith("Ergebnis:")]
    if not bil:
        return False, f"ABGEBROCHEN rc={rc} (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return rc == 1 and fails > 0, f"{fails} FAIL · {bil[-1]}"


def main() -> int:
    if MARKE.exists():
        print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
        zurueck()
        MARKE.unlink()
    fremd = {p[1] for p in PROBEN} - set(DATEIEN)
    if fremd:
        print(f"ABBRUCH: Proben fassen Dateien ausserhalb der Sicherung an: {sorted(fremd)}")
        return 2
    rc, aus = lauf()
    if rc != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (rc={rc}) – keine Gegenprobe deutbar")
        print("\n".join(aus.splitlines()[-15:]))
        return 2
    sichern()
    atexit.register(aufraeumen)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(3))
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    stumm = 0
    for name, rel, alt, neu in PROBEN:
        p = ROOT / rel
        text = p.read_text(encoding="utf-8")
        if text.count(alt) != 1:
            print(f"  ? {name}: Anker {text.count(alt)}x gefunden – Probe trifft nicht")
            stumm += 1
            continue
        p.write_text(text.replace(alt, neu), encoding="utf-8")
        try:
            biss, info = bewerte()
        finally:
            shutil.copy2(_ablage(rel), p)
        print(f"  {'✓ beisst' if biss else '✗ STUMM '}  {name}  ({info})")
        stumm += 0 if biss else 1
    aufraeumen()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("ABBRUCH: Arbeitsbaum nach dem Lauf NICHT byte-gleich – Sicherung pruefen:", ABL)
        return 2
    print(f"\nErgebnis: {len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
