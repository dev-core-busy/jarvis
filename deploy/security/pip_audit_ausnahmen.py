#!/usr/bin/env python3
"""Liest deploy/security/pip_audit_ausnahmen.txt und gibt die pip-audit-Argumente aus.

Aufruf (CI):  ARGS=$(python3 deploy/security/pip_audit_ausnahmen.py --argumente)

Jede Zeile braucht ID, Pruefdatum und Grund. Fehlt etwas: Exit 2 (die Liste ist
kaputt, der Audit-Lauf waere nicht deutbar). Ist ein Datum ueberschritten: Exit 1
mit Nennung der ID – die Bewertung ist abgelaufen, nicht still verlaengert.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

DATEI = Path(__file__).with_name("pip_audit_ausnahmen.txt")
ZEILE = re.compile(r"^(?P<id>[A-Z][A-Z0-9]*-[0-9A-Za-z-]+)\s+(?P<bis>\d{4}-\d{2}-\d{2})\s+#\s*(?P<grund>\S.*)$")


def laden(heute: dt.date | None = None) -> tuple[list[str], list[str], list[str]]:
    """-> (gueltige IDs, abgelaufene IDs, Formatfehler)"""
    heute = heute or dt.date.today()
    gueltig, abgelaufen, fehler = [], [], []
    for nr, roh in enumerate(DATEI.read_text(encoding="utf-8").splitlines(), 1):
        z = roh.strip()
        if not z or z.startswith("#"):
            continue
        m = ZEILE.match(z)
        if not m:
            fehler.append(f"Zeile {nr}: '{z}' (erwartet: ID  JJJJ-MM-TT  # Grund)")
            continue
        try:
            bis = dt.date.fromisoformat(m["bis"])
        except ValueError:
            fehler.append(f"Zeile {nr}: Datum {m['bis']} ungueltig")
            continue
        (abgelaufen if bis < heute else gueltig).append(m["id"])
    return gueltig, abgelaufen, fehler


def main() -> int:
    gueltig, abgelaufen, fehler = laden()
    if fehler:
        print("pip_audit_ausnahmen.txt fehlerhaft:\n  " + "\n  ".join(fehler), file=sys.stderr)
        return 2
    if abgelaufen:
        print("Ausnahme abgelaufen – neu bewerten oder Paket heben: " + ", ".join(abgelaufen),
              file=sys.stderr)
        return 1
    if "--argumente" in sys.argv:
        print(" ".join(f"--ignore-vuln {i}" for i in gueltig))
    else:
        print(f"{len(gueltig)} Ausnahmen gueltig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
