#!/usr/bin/env python3
"""Wegwerf-Messung: SCHREIBT test_rag_ordner.py irgendwo ausserhalb des Sandkastens?

Gemessen wird ueber einen Audit-Hook (PEP 578) – der sieht JEDEN Schreibzugriff,
unabhaengig davon, ueber welches Modul er laeuft. Eine Quelltext-Pruefung
("ruft es config.save_skill_state?") koennte die Frage nicht beantworten, weil
der Aufruf ueber eine ausgetauschte sys.modules-Attrappe laufen kann.

Mit Positivkontrolle: der Hook muss einen bekannten Schreibzugriff SEHEN,
sonst misst er nichts und eine leere Liste waere wertlos.
"""
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.gettempdir()).resolve()

schreibzugriffe = []
aktiv = [False]


def hook(event, args):
    if not aktiv[0]:
        return
    try:
        if event == "open":
            pfad, modus, _flags = args
            if modus and any(c in str(modus) for c in "wax+"):
                schreibzugriffe.append(("open:" + str(modus), str(pfad)))
        elif event in ("os.rename", "os.replace", "shutil.move", "os.remove",
                       "os.unlink", "os.mkdir", "os.rmdir", "shutil.rmtree"):
            schreibzugriffe.append((event, " ".join(str(a) for a in args)))
    except Exception:                                # noqa: BLE001
        pass


sys.addaudithook(hook)

# ── Positivkontrolle: sieht der Hook ueberhaupt etwas? ───────────────────────
# ⚠ ZWEITEILIG. Die erste Fassung dieser Probe hat NUR geprueft, ob der Hook
# irgendetwas sieht – und dann JEDEN Pfad per Path().resolve() gegen das
# Arbeitsverzeichnis aufgeloest. `shutil.rmtree` meldet seine Ereignisse aber
# FD-RELATIV (blosse Dateinamen); daraus wurden Phantom-Pfade im Projektbaum,
# und die Probe meldete "SCHREIBT ausserhalb des Sandkastens" fuer einen Lauf,
# der nachweislich nichts angefasst hat (git status: keine Loeschung, keine der
# gemeldeten Dateien existiert). Deshalb: relative Pfade zaehlen NICHT, und die
# Kontrolle muss einen ABSOLUTEN Treffer ausserhalb /tmp nachweisen koennen.
aktiv[0] = True
probe = Path(tempfile.mkdtemp(prefix="probe-")) / "kontrolle.txt"
probe.write_text("x")
kontroll_ziel = ROOT / ".probe-kontrolle.tmp"
kontroll_ziel.write_text("x")
aktiv[0] = False
if not any("kontrolle.txt" in p for _, p in schreibzugriffe):
    print("ABBRUCH: der Audit-Hook sieht keinen Schreibzugriff – Messung wertlos")
    sys.exit(2)
if not any(str(kontroll_ziel) in p for _, p in schreibzugriffe):
    print("ABBRUCH: der Hook sieht einen Schreibzugriff AUSSERHALB /tmp nicht – "
          "eine leere Fundliste waere damit wertlos")
    sys.exit(2)
kontroll_ziel.unlink()
print("Positivkontrolle: Hook sieht Schreibzugriffe, auch ausserhalb /tmp  ✓")
schreibzugriffe.clear()

# ── Der eigentliche Lauf ────────────────────────────────────────────────────
sys.argv = [str(ROOT / "tests" / "test_rag_ordner.py")]
aktiv[0] = True
try:
    runpy.run_path(str(ROOT / "tests" / "test_rag_ordner.py"), run_name="__main__")
except SystemExit as e:
    rc = e.code
aktiv[0] = False

# ── Auswertung: was lag AUSSERHALB von /tmp? ────────────────────────────────
fremd, relativ = [], 0
for ereignis, pfad in schreibzugriffe:
    p = pfad.split(" ")[0]
    # ⚠ NUR ABSOLUTE PFADE SIND EINE AUSSAGE. Ein relativer Name stammt aus
    # einem fd-relativen Aufruf (rmtree) und laesst sich von aussen keinem Ort
    # zuordnen – gegen das Arbeitsverzeichnis aufgeloest ergibt er einen
    # Phantom-Treffer im Projektbaum.
    if not p.startswith("/"):
        relativ += 1
        continue
    try:
        aufgeloest = Path(p).resolve()
    except Exception:                                # noqa: BLE001
        continue
    if str(aufgeloest).startswith(str(TMP)):
        continue
    if "__pycache__" in str(aufgeloest):             # Bytecode, kein Zustand
        continue
    fremd.append((ereignis, str(aufgeloest)))

print("\nSchreibzugriffe gesamt: %d" % len(schreibzugriffe))
print("davon fd-relativ (rmtree, nicht zuordenbar): %d" % relativ)
print("davon ABSOLUT ausserhalb /tmp (ohne __pycache__): %d" % len(fremd))
for ereignis, pfad in fremd[:40]:
    print("   %-18s %s" % (ereignis, pfad))
print("\nBEFUND: %s" % ("SAUBER – kein Zustand ausserhalb des Sandkastens"
                        if not fremd else "SCHREIBT ausserhalb des Sandkastens"))
sys.exit(0 if not fremd else 1)
