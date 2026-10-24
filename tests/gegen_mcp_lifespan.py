#!/usr/bin/env python3
"""Gegenprobe zu tests/test_mcp_lifespan.py: beisst der Waechter?

Jede Probe dreht EINEN Teil des Fixes zurueck und erwartet mindestens einen
FAIL. Vorher gruener Basislauf, danach Byte-Gleichheit per md5, ohne Bytecode.

Die wichtigste Probe ist die ERSTE: sie stellt den Zustand vom 2026-10-24 her
(nur `except Exception` in `connect`). Beisst sie nicht, ist der Waechter
blind fuer genau den Vorfall, fuer den er gebaut ist.

⚠ ZWEI ARTEN, getrennt ausgewiesen:
  * PRODUKT – eine echte Luecke im Code.
  * SONDE – eine Schwaechung am Messaufbau des Waechters. Sie belegt, dass die
    Positivkontrollen anschlagen; ohne sie waeren die Folgepruefungen trivial.
    Die REGEL selbst wird nicht sabotiert (ein Waechter kann das Entfernen
    seiner eigenen Regel nicht melden – falsch platzierte Probe).

Exit 0 = alle beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    venv/bin/python tests/gegen_mcp_lifespan.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_mcp_lifespan.py"
MC = "backend/mcp_client.py"
MA = "backend/main.py"
WI = "tests/test_mcp_lifespan.py"
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable

PROBEN = [
    # ── PRODUKT: der Zustand vom 2026-10-24 ────────────────────────────────
    # ⚠ DIE SABOTAGE MUSS DIE SCHRANKE ENTFERNEN, NICHT DEN CODE KAPUTT MACHEN.
    # Erster Versuch: `except _NIE_CancelledError` (NameError) und `if True:`
    # vor einem `except` (SyntaxError) – beide liessen den Waechter mit Exit 2
    # abbrechen, und ein Abbruch ist von einem bestandenen Lauf nicht zu
    # unterscheiden (Register). `asyncio.TimeoutError` ist syntaktisch gueltig,
    # existiert und trifft hier NIE: genau die Entfernung der Schranke.
    ("PRODUKT connect() faengt nur Exception (der Vorfall)", MC,
     "        except asyncio.CancelledError:\n"
     "            # ⚠ BEZAHLTER VORFALL (DEV 2026-10-24, 34 Neustarts in sechs\n",
     "        except asyncio.TimeoutError:\n"
     "            # ⚠ BEZAHLTER VORFALL (DEV 2026-10-24, 34 Neustarts in sechs\n"),
    ("PRODUKT connect() faengt keine BaseExceptionGroup", MC,
     "        except BaseExceptionGroup as gruppe:\n"
     "            # Dieselbe TaskGroup liefert beim Aufraeumen eine Gruppe",
     "        except asyncio.TimeoutError as gruppe:\n"
     "            # Dieselbe TaskGroup liefert beim Aufraeumen eine Gruppe"),
    # Dieser Zweig traegt den Fehler aus `connect_server` SELBST (Eintrag ohne
    # `id`), NICHT die BaseException-Faelle – die liegen allein in `connect()`.
    # Eine Probe auf eine doppelte Schranke bleibt stumm, und das liest sich
    # wie ein blinder Waechter (beim Bau genau so passiert, Dopplung entfernt).
    ("PRODUKT connect_all bricht beim ersten Fehler ab", MC,
     "            except Exception as e:  # noqa: BLE001\n"
     "                # ⚠ HIER BEWUSST NUR `Exception`",
     "            except asyncio.TimeoutError as e:\n"
     "                # ⚠ HIER BEWUSST NUR `Exception`"),
    ("PRODUKT startup_mcp faengt nur Exception", MA,
     "    except BaseException as e:  # noqa: BLE001\n"
     "        print(f\"[MCP] Startup-Fehler: {type(e).__name__}: {e} – der Dienst \"\n",
     "    except Exception as e:  # noqa: BLE001\n"
     "        print(f\"[MCP] Startup-Fehler: {type(e).__name__}: {e} – der Dienst \"\n"),
    # ── PRODUKT: die Gegenrichtung – der Shutdown muss abbrechen ───────────
    # Ohne `cancelling()` wird JEDE CancelledError geschluckt, auch der echte
    # Abbruch: das Herunterfahren haengt. Dieselbe Zeile, andere Richtung.
    ("PRODUKT CancelledError wird blind geschluckt (Shutdown haengt)", MC,
     "            aufgabe = asyncio.current_task()\n"
     "            if aufgabe is not None and aufgabe.cancelling():\n"
     "                raise\n"
     "            self.error = (\"Verbindung abgebrochen",
     "            aufgabe = asyncio.current_task()\n"
     "            if False:\n"
     "                raise\n"
     "            self.error = (\"Verbindung abgebrochen"),
    ("PRODUKT harte Anteile einer Gruppe werden geschluckt", MC,
     "            harte, _ = gruppe.split((KeyboardInterrupt, SystemExit))\n"
     "            if harte is not None:\n"
     "                raise\n"
     "            self.error = \"; \".join(str(e) for e in gruppe.exceptions)",
     "            harte, _ = gruppe.split((KeyboardInterrupt, SystemExit))\n"
     "            if False:\n"
     "                raise\n"
     "            self.error = \"; \".join(str(e) for e in gruppe.exceptions)"),
    # ── SONDE: schlaegt die Positivkontrolle an? ───────────────────────────
    ("SONDE der gesunde Server verbindet gar nicht mehr", WI,
     "        c._session = _ClientSession(object(), object())\n",
     "        pass\n"),
    ("SONDE der Cancel-Aufbau cancelt nicht (Gegenkontrolle trivial)", WI,
     "    aufgabe.cancel()\n", "    pass\n"),
]

DATEIEN = [MC, MA, WI]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, object]:
    """FAIL-Zahl des Waechters. -1 = konnte nicht laufen (Exit 2 / keine Bilanz)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([PY, str(WAECHTER)], capture_output=True, text=True,
                           timeout=300, cwd=str(ROOT), env=env)
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), 0


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an: %s"
              % sorted({p[1] for p in PROBEN} - set(DATEIEN)))
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s) – ohne gruene "
              "Basis ist keine Gegenprobe deutbar" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %-56s Anker %dx" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-56s %d FAIL" % (name, fails))
            elif fails < 0:
                # Ein Abbruch ist hier KEIN Biss: "konnte nicht laufen" ist von
                # "bestanden" nicht zu unterscheiden (Register).
                print("  ABBR %-56s konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-56s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
