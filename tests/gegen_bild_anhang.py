#!/usr/bin/env python3
"""Gegenproben zu tests/test_bild_anhang.py – beisst der Waechter EINZELN?

Jede Probe dreht GENAU EINE Aenderung zurueck und misst, ob der Waechter das
meldet. Eine Gegenprobe, die nicht beisst, ist ein Testmangel – kein Beweis.

DREI REGELN, jede im Projekt bezahlt:

* **Gemessen wird der EXIT-CODE und die BILANZZEILE**, nie die Zahl der
  FAIL-Zeilen: ein Lauf, der ohne Bilanz abbricht, ist von "nicht gelaufen"
  nicht zu unterscheiden und sieht beim Zaehlen wie ein Erfolg aus.
* **Jede Ersetzung hat eine TREFFERKONTROLLE** (`assert`). Ohne sie "beisst"
  eine Probe scheinbar nicht, weil sie ihr Ziel gar nicht getroffen hat.
* **Jede Datei, die eine Probe anfasst, MUSS in der Sicherung stehen** – das
  wird als Regel geprueft, nicht gepflegt (2026-09-11: eine fehlende Datei
  liess eine Sabotage stehen, und der naechste Lauf meldete einen Fehler, den
  es im Code nicht gab).
"""
import atexit
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bild_anhang.py"
ABLAGE = Path.home() / ".gegen-bild-anhang"
MARKE = ABLAGE / ".laeuft"

DATEIEN = [
    "backend/main.py",
    "backend/lauf_tmp.py",
    "backend/sandbox.py",
    "backend/attachments.py",
    # Der WAECHTER selbst wird ebenfalls sabotiert (Probe "Filter ohne
    # Docstrings") – also gehoert er gesichert. Genau diese Zeile fehlte am
    # 2026-09-11 in einem anderen Harness und liess eine Sabotage stehen.
    "tests/test_bild_anhang.py",
]


def sichern() -> None:
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")     # Pfad, nicht Basisname:
        ziel.write_bytes((ROOT / rel).read_bytes())  # zwei gleichnamige Dateien
    MARKE.write_text("1")                            # wuerden sich sonst decken


def zurueck() -> None:
    for rel in DATEIEN:
        quelle = ABLAGE / rel.replace("/", "__")
        if quelle.is_file():
            (ROOT / rel).write_bytes(quelle.read_bytes())
    for rel in DATEIEN:
        quelle = ABLAGE / rel.replace("/", "__")
        if quelle.is_file() and (ROOT / rel).read_bytes() != quelle.read_bytes():
            print(f"⚠ WIEDERHERSTELLUNG UNVOLLSTAENDIG: {rel}")
            sys.exit(2)


def _ende(*_a):
    zurueck()
    MARKE.unlink(missing_ok=True)


atexit.register(_ende)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck")
    zurueck()
    MARKE.unlink(missing_ok=True)


def lauf() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, timeout=180)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def bilanz(text: str):
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def patch(rel: str, alt: str, neu: str, anzahl: int = 1) -> None:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"ANKER VERFEHLT in {rel}: {alt[:60]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


# ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ──────────────
sichern()
rc, aus = lauf()
b = bilanz(aus)
if rc != 0 or not b or b[1] != 0:
    print(f"ABBRUCH: Basislauf nicht gruen (rc={rc}, bilanz={b})")
    print(aus[-3000:])
    sys.exit(2)
print(f"Basis gruen: {b[0]} OK, 0 FAIL\n")


PROBEN = []


def probe(name: str, rel: str, alt: str, neu: str, anzahl: int = 1):
    PROBEN.append((name, rel, alt, neu, anzahl))


# 1 – DER EIGENTLICHE FEHLER, als ALTSTAND: das Bild bleibt inline, es
#     entsteht keine Datei. Die Sabotage umgeht den Aufruf, LAESST DEN NAMEN
#     ABER STEHEN – genau daran ist die erste Fassung des Waechters
#     gescheitert (sie prueste das Vorkommen statt der Wirkung).
probe("Bild bekommt keine Datei (ALTSTAND, Aufruf umgangen)", "backend/main.py",
      "        ziel, arbeit = _anhang_ablegen(_b64.b64decode(b64daten), dateiname, benutzer)",
      "        ziel, arbeit = (None, None) if True else _anhang_ablegen(\n"
      "            _b64.b64decode(b64daten), dateiname, benutzer)")
# 1b – der Zweig ruft die Funktion gar nicht mehr
probe("WS-Handler ruft _bild_als_datei nicht", "backend/main.py",
      "                        _hinweis_i = _bild_als_datei(",
      "                        _hinweis_i = \"\" or _keine_datei(")
# 2
probe("Anhang wird nicht fuer Folgefragen gemerkt", "backend/main.py",
      "        _anhang_merken(sitzung, dateiname, ziel.name,",
      "        _egal_merken(sitzung, dateiname, ziel.name,")
# 3
probe("kein Pfad im Hinweis", "backend/main.py",
      "    return (f\"[Bild '{dateiname}' liegt auch als Datei unter: {pfad}.{bearb} \"",
      "    return (f\"[Bild '{dateiname}' liegt vor.{bearb} \"")
# 3b
probe("Hinweis verschweigt, dass der Pfad zum Ansehen unnoetig ist",
      "backend/main.py",
      "            f\"Zum blossen ANSEHEN brauchst du den Pfad nicht – das Bild liegt \"\n"
      "            f\"dir bereits vor.]\")",
      "            f\"Nutze ihn.]\")")
# 4
probe("Werkzeug wird blind genannt (auch wenn es fehlt)", "backend/main.py",
      'if werkzeuge and "bild_text_ersetzen" in werkzeuge:',
      'if True:')
# 4b – fail-open aufgehoben: ein Fehler reisst den Handler mit
probe("Ablage ist nicht mehr fail-open", "backend/main.py",
      "    except Exception as e:  # noqa: BLE001\n"
      "        print(f\"[attach] Bild-Arbeitskopie fehlgeschlagen ({dateiname}): {e}\", flush=True)\n"
      "        return \"\"",
      "    except ZeroDivisionError as e:  # noqa: BLE001\n"
      "        print(f\"[attach] {e}\", flush=True)\n"
      "        return \"\"")
# 5 – Wurzel wieder auflistbar
probe("ist_verwaltungswurzel liefert immer False", "backend/lauf_tmp.py",
      "    for wurzel in (ANH_ROOT, ARBEIT_ROOT):\n        try:\n            if rp == wurzel.resolve():",
      "    for wurzel in ():\n        try:\n            if rp == wurzel.resolve():")
# 6
probe("sandbox prueft die Wurzel nicht (ALTSTAND)", "backend/sandbox.py",
      "        if _lt.ist_verwaltungswurzel(rp):",
      "        if False and _lt.ist_verwaltungswurzel(rp):")
# 7 – Aufraeumen
probe("cleanup ruft das Aufraeumen nicht", "backend/attachments.py",
      "    _leere_kennungen_entfernen(grenze, uid)",
      "    pass  # kein Aufraeumen")
# 8
probe("rmdir -> rmtree (nimmt volle Verzeichnisse mit)", "backend/attachments.py",
      "            d.rmdir()                              # scheitert, wenn NICHT leer",
      "            __import__('shutil').rmtree(d)")
# 9
probe("Eigentuemer wird nicht geprueft", "backend/attachments.py",
      "            if st.st_uid != uid or st.st_mtime >= grenze:",
      "            if st.st_mtime >= grenze:")
# 10
probe("Frist wird ignoriert", "backend/attachments.py",
      "            if st.st_uid != uid or st.st_mtime >= grenze:",
      "            if st.st_uid != uid:")
# 11
probe("Symlink wird verfolgt (lstat -> stat)", "backend/attachments.py",
      "            st = d.lstat()\n            import stat as _stat\n            if not _stat.S_ISDIR(st.st_mode):",
      "            st = d.stat()\n            import stat as _stat\n            if not _stat.S_ISDIR(st.st_mode):")
# 12 – DER EIGENE MANGEL AUS LAUF 1: sabotiert wird der FILTER, nicht der
#      Docstring. Ohne Docstring-Entfernung liest der Waechter seine eigene
#      Begruendung ("rmdir statt rmtree" steht dreimal im Docstring) und meldet
#      einen Fehler, den es im Code nicht gibt.
probe("Waechter-Filter entfernt keine Docstrings", "tests/test_bild_anhang.py",
      "            if (isinstance(erste, ast.Expr)",
      "            if (False and isinstance(erste, ast.Expr)")


# ── REGEL: jede angefasste Datei MUSS gesichert sein ──────────────────────
# Sie stand bis eben nur im Docstring – also als Behauptung, nicht als Schranke.
# Ein Rueckstand in einer ungesicherten Datei meldet sich erst beim naechsten
# Lauf, und dann als Fehler, den es im Code nicht gibt.
_angefasst = {rel for _n, rel, _a, _b, _c in PROBEN}
_ungesichert = _angefasst - set(DATEIEN)
if _ungesichert:
    print(f"ABBRUCH: Proben fassen ungesicherte Dateien an: {sorted(_ungesichert)}")
    sys.exit(2)

print("=" * 72)
beissen = 0
stumm = []
for name, rel, alt, neu, anzahl in PROBEN:
    try:
        patch(rel, alt, neu, anzahl)
    except AssertionError as e:
        print(f"  ⚠ PROBE VERFEHLT IHR ZIEL: {name}\n      {e}")
        zurueck()
        stumm.append(name + " (Anker verfehlt)")
        continue
    rc, aus = lauf()
    b = bilanz(aus)
    zurueck()
    if b is None:
        print(f"  ✗ {name}: ABBRUCH OHNE BILANZ (rc={rc}) – Waechter unbrauchbar")
        stumm.append(name + " (ohne Bilanz)")
    elif rc != 0 and b[1] > 0:
        print(f"  ✓ {name}: {b[1]} FAIL")
        beissen += 1
    else:
        print(f"  ✗ {name}: BEISST NICHT (rc={rc}, {b[0]} OK, {b[1]} FAIL)")
        stumm.append(name)

print("=" * 72)
print(f"{beissen} von {len(PROBEN)} Gegenproben beissen einzeln")
if stumm:
    print("STUMM/VERFEHLT:")
    for s in stumm:
        print("  -", s)
zurueck()
MARKE.unlink(missing_ok=True)
sys.exit(1 if stumm else 0)
