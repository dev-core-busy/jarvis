#!/usr/bin/env python3
"""Gegenproben zum Fix "Bild angekuendigt, keines da" (Vorfall 2026-09-15).

Jede Sabotage muss EINZELN beissen. Eine Probe, die nicht beisst, ist ein
Testmangel - kein Beweis.

⚠ SICHERUNG AUF PLATTE + LAUFMARKE: wird der Lauf abgeschossen (Timeout,
kill -9), bleibt der Arbeitsbaum sonst SABOTIERT zurueck, und der naechste
Testlauf meldet Fehler, die es im Code nicht gibt. Die Marke wird beim
geordneten Ende abgeraeumt; liegt sie beim Start noch da, wird zuerst
zurueckgestellt.
"""
import atexit
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-bildzusage"
MARKE = ABLAGE / ".laeuft"

DATEIEN = ["backend/agent.py", "tests/test_bild_anzeige.py"]
WAECHTER = "tests/test_bild_anzeige.py"


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        z = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, z)     # IMMER erneuern, nie "nur wenn fehlt"
    MARKE.write_text("1")


def zurueck():
    for rel in DATEIEN:
        z = ABLAGE / rel.replace("/", "__")
        if z.exists():
            shutil.copy2(z, ROOT / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf():
    r = subprocess.run([sys.executable, str(ROOT / WAECHTER)],
                       capture_output=True, text=True, timeout=300)
    aus = r.stdout + r.stderr
    m = re.search(r"(\d+) ok, (\d+) Fehler", aus)
    if not m:
        return None, aus      # keine Bilanz = nicht gelaufen, NICHT "bestanden"
    return int(m.group(2)), aus


def patch(rel, alt, neu, anzahl=1):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"ANKER VERFEHLT in {rel}: {alt[:70]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


# ⚠ REGEL statt gepflegter Liste: was eine Probe anfasst, MUSS gesichert sein.
PROBEN = []


def probe(name, rel, alt, neu):
    PROBEN.append((name, rel, alt, neu))


probe("Hinweis-Zweig ganz raus", "backend/agent.py",
      '            if nannte_bild and "/api/generated/" not in t:',
      '            if False and nannte_bild and "/api/generated/" not in t:')

probe("gemessen wird ERST NACH dem Entfernen", "backend/agent.py",
      '            nannte_bild = "/api/generated/" in t\n            t = self._ohne_tote_bildrefs(t)',
      '            t = self._ohne_tote_bildrefs(t)\n            nannte_bild = "/api/generated/" in t')

probe("Hinweis auch, wenn ein Bild nachgetragen wurde", "backend/agent.py",
      '            if nannte_bild and "/api/generated/" not in t:',
      '            if nannte_bild:')

probe("Prompt-Regel 'erfinde keine Adresse' raus", "backend/agent.py",
      "    - ERFINDE NIEMALS SELBST EINE `/api/generated/...`-ADRESSE.",
      "    - Hinweis zu Adressen.")

probe("Prompt-Regel 'kein Bearbeiten' raus", "backend/agent.py",
      "    - DU KANNST EIN VORHANDENES BILD NICHT BEARBEITEN.",
      "    - Hinweis zur Bildbearbeitung.")


def main():
    fehlend = {r for _, r, _, _ in PROBEN} - set(DATEIEN)
    if fehlend:
        print(f"ABBRUCH: Proben fassen ungesicherte Dateien an: {fehlend}")
        return 2

    if MARKE.exists():
        print("Rueckstand eines abgebrochenen Laufs gefunden - stelle zurueck.")
        zurueck()

    sichern()
    atexit.register(zurueck)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(1))

    basis, aus = lauf()
    if basis is None:
        print("ABBRUCH: Basislauf ohne Bilanzzeile\n" + aus[-1500:])
        return 2
    if basis != 0:
        print(f"ABBRUCH: Basis ist NICHT gruen ({basis} Fehler) - "
              f"ohne gruene Basis ist keine Gegenprobe deutbar")
        return 2
    print(f"Basis gruen (0 Fehler).\n")

    schlecht = []
    for name, rel, alt, neu in PROBEN:
        zurueck()
        try:
            patch(rel, alt, neu)
        except AssertionError as e:
            print(f"  ✗ {name:52s} ANKER VERFEHLT - {e}")
            schlecht.append(name)
            continue
        f, a = lauf()
        if f is None:
            print(f"  ✗ {name:52s} kein Ergebnis (Lauf abgebrochen)")
            schlecht.append(name)
        elif f == 0:
            print(f"  ✗ {name:52s} BEISST NICHT (0 Fehler)")
            schlecht.append(name)
        else:
            print(f"  ✓ {name:52s} {f} FAIL")

    # Kompletter Altstand
    zurueck()
    patch("backend/agent.py",
          '            nannte_bild = "/api/generated/" in t\n', "")
    patch("backend/agent.py",
          '            if nannte_bild and "/api/generated/" not in t:\n'
          '                t = (t.rstrip() + "\\n\\n" + self._KEIN_BILD_HINWEIS).strip()\n', "")
    f, _ = lauf()
    if f:
        print(f"  ✓ {'kompletter Altstand':52s} {f} FAIL")
    else:
        print(f"  ✗ {'kompletter Altstand':52s} BEISST NICHT")
        schlecht.append("Altstand")

    zurueck()
    nach, _ = lauf()
    print(f"\nnach dem Zurueckstellen: {nach} Fehler "
          f"({'ok' if nach == 0 else 'RUECKSTAND!'})")
    print(f"\n{len(PROBEN) + 1 - len(schlecht)}/{len(PROBEN) + 1} Proben beissen")
    return 1 if schlecht else 0


if __name__ == "__main__":
    sys.exit(main())
