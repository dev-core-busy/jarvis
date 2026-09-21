"""Gegenproben zur Index-Automatik: jede Sabotage muss EINZELN beissen.

Harness-Regeln (aus dem Register, jede einzeln bezahlt):
  * JEDE Datei, die eine Probe anfasst, steht in DATEIEN - als REGEL geprueft,
    nicht gepflegt (Exit 2, wenn eine fehlt).
  * Laufmarke: nach einem `kill -9` bleibt sie liegen und der naechste Start
    nimmt den Rueckstand zurueck, statt fertige Arbeit zunichtezumachen.
  * Vorab ein GRUENER Basislauf - ohne gruene Basis ist keine Gegenprobe deutbar.
  * Gemessen wird Exit-Code UND Bilanzzeile: ein Lauf, der ohne Bilanz abbricht,
    ist von "nicht gelaufen" nicht zu unterscheiden.
  * Jede Ersetzung hat eine Trefferkontrolle - eine Sabotage, die ihr Ziel
    verfehlt, sieht sonst wie ein zahnloser Waechter aus.
"""
import atexit
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ⚠ Ablage im HOME (0700), NICHT im Arbeitsbaum: dort waere sie eine verirrte
# Datei, die `deploy/abgleich.py` meldet - und nicht nach /tmp (1777), wo ein
# Rest eines fremden Laufs den naechsten Lauf blockiert.
SICHER = Path.home() / ".gegen-rag-autoindex"
MARKE = SICHER / ".laeuft"
WAECHTER = ROOT / "tests" / "test_rag_autoindex.py"

DATEIEN = [
    "backend/rag_autoindex.py",
    "backend/tools/knowledge.py",
    "backend/main.py",
    "tests/test_rag_autoindex.py",
]


def sichern():
    SICHER.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = SICHER / rel.replace("/", "__")     # Pfad, nicht Basisname
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("laeuft", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf():
    """(exit, bilanz-zeile). Eine fehlende Bilanz zaehlt als Abbruch."""
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, timeout=180, cwd=ROOT)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if not m:
        return r.returncode, None
    return r.returncode, (int(m.group(1)), int(m.group(2)))


def patch(rel, alt, neu, anzahl=1):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    treffer = s.count(alt)
    assert treffer == anzahl, f"SABOTAGE TRIFFT NICHT ({treffer}x statt {anzahl}x): {alt[:70]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


PROBEN = [
    ("Startup-Hook entfernt (Takt laeuft nie)", [
        ("backend/main.py", "async def startup_rag_autoindex():",
         "async def _aus_startup_rag_autoindex():")]),
    ("Index wird geleert statt ergaenzt (incremental=False)", [
        ("backend/rag_autoindex.py", "K.force_reindex(incremental=True)",
         "K.force_reindex(incremental=False)")]),
    ("⚠ Loeschungen loesen keinen Lauf mehr aus", [
        ("backend/rag_autoindex.py",
         'if not stand["geaendert"] and not stand["verwaist"]:',
         'if not stand["geaendert"]:')]),
    ("Ordner nicht mehr streng geprueft (getrenntes Share gilt als geloescht)", [
        ("backend/rag_autoindex.py",
         "alive = K._nutzbare_ordner(folders, indexed, streng=True)",
         "alive = K._nutzbare_ordner(folders, indexed, streng=False)")]),
    ("Drift: der Reindex baut die Aenderungs-Regel wieder nach", [
        ("backend/tools/knowledge.py",
         "    to_index = _geaenderte_dateien(files, indexed)",
         "    to_index = [f for f in files if indexed.get(str(f)) != f.stat().st_mtime]")]),
    ("Drift: der Reindex baut die Verwaist-Regel wieder nach", [
        ("backend/tools/knowledge.py",
         "        stale = _verwaiste_dateien(current_paths, indexed, alive)",
         "        stale = [p for p in indexed if p not in current_paths]")]),
    ("Praefix-Falle: share_1 frisst share_10", [
        ("backend/tools/knowledge.py",
         "    alive_prefixes = tuple(str(r).rstrip(os.sep) + os.sep for r in alive)",
         "    alive_prefixes = tuple(str(r).rstrip(os.sep) for r in alive)")]),
    ("stummes Netzlaufwerk gilt als geaendert (Dauer-Reindex)", [
        ("backend/tools/knowledge.py",
         """        except Exception:  # noqa: BLE001
            continue
        if indexed.get(str(filepath)) != mtime:""",
         """        except Exception:  # noqa: BLE001
            geaendert.append(filepath)
            continue
        if indexed.get(str(filepath)) != mtime:""")]),
    ("kein Schutz gegen einen bereits laufenden Indexlauf", [
        ("backend/rag_autoindex.py",
         'if K.get_index_progress().get("running"):',
         'if False:')]),
    ("takt_sek als Konstante (Umstellung wirkt erst nach Neustart)", [
        ("backend/rag_autoindex.py",
         '    roh = os.environ.get("JARVIS_RAG_AUTOINDEX_SEK")',
         '    roh = None; _ = os.environ.get("JARVIS_RAG_AUTOINDEX_SEK")')]),
    ("gewartet wird VOR dem Lauf (Takt kann sich selbst ueberholen)", [
        ("backend/main.py",
         """            try:
                ergebnis = await asyncio.to_thread(_ai.lauf)""",
         """            await asyncio.sleep(max(30, _ai.takt_sek()))
            try:
                ergebnis = await asyncio.to_thread(_ai.lauf)"""),
        ("backend/main.py",
         """            await asyncio.sleep(max(30, _ai.takt_sek()))

    try:
        asyncio.create_task(_loop())""",
         """
    try:
        asyncio.create_task(_loop())""")]),
    ("die Vorpruefung indiziert selbst (zweiter Indizierweg)", [
        ("backend/rag_autoindex.py",
         "    geaendert = K._geaenderte_dateien(files, indexed)",
         "    geaendert = K._geaenderte_dateien(files, indexed)\n    K.force_reindex()")]),
    ("Schluessel-Kollision zurueck (Grund wird leergemischt)", [
        ("backend/rag_autoindex.py", '        "hinweis": "",', '        "grund": "",'),
        ("backend/rag_autoindex.py",
         '        return {**stand, "indiziert": False, "grund": "nichts geaendert"}',
         '        return {"indiziert": False, "grund": "nichts geaendert", **stand}')]),
    ("fehlender Vektor-Index wird als 'nichts geaendert' gemeldet", [
        ("backend/rag_autoindex.py",
         '    if stand.get("hinweis"):',
         '    if False:')]),
    ("Zustand ist keine Kopie (Aufrufer kann hineinschreiben)", [
        ("backend/rag_autoindex.py", "        d = dict(_zustand)", "        d = _zustand")]),
]


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - wird zurueckgenommen")
        zurueck()

    # REGEL statt gepflegter Liste: jede angefasste Datei muss gesichert sein.
    angefasst = {rel for _, aend in PROBEN for rel, _, _ in aend}
    fehlt = angefasst - set(DATEIEN)
    if fehlt:
        print(f"Exit 2: Proben fassen ungesicherte Dateien an: {sorted(fehlt)}")
        return 2

    sichern()
    atexit.register(zurueck)
    signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(143)))

    code, bilanz = lauf()
    if bilanz is None or bilanz[1] != 0:
        print(f"Exit 2: BASISLAUF NICHT GRUEN ({bilanz}) - keine Gegenprobe deutbar")
        return 2
    basis_ok = bilanz[0]
    print(f"Basislauf gruen: {basis_ok} OK\n")

    beissen = 0
    for name, aenderungen in PROBEN:
        zurueck()
        sichern()
        try:
            for rel, alt, neu in aenderungen:
                patch(rel, alt, neu)
        except AssertionError as e:
            print(f"  ⚠ {name}: {e}")
            continue
        code, bilanz = lauf()
        if bilanz is None:
            print(f"  OK(Abbruch) {name}: Waechter bricht ab (Exit {code}, keine Bilanz)")
            beissen += 1
        elif bilanz[1] > 0:
            print(f"  OK   {name}: {bilanz[1]} FAIL")
            beissen += 1
        else:
            print(f"  ZAHNLOS {name}: 0 FAIL")
    zurueck()

    print(f"\nGegenproben: {beissen} von {len(PROBEN)} beissen")
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
