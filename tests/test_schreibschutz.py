#!/usr/bin/env python3
"""Waechter: ``tests/lib/schreibschutz`` laesst keinen Harness fremde Arbeit
ueberschreiben – und jeder ``gegen_*``-Harness schaltet ihn ein.

Vorfall 2026-11-18 (Register, Abschnitt Tests und Waechter): ein Harness
sicherte beim Start, die Proben lasen danach eine NEUERE Fassung (Commit des
Betreibers), und das Ende schrieb die Startsicherung darueber.

Jedes Szenario laeuft in einem EIGENEN Prozess (die Haken gelten
prozessweit) mit Wegwerf-Wurzel und Wegwerf-Journal – nie im Arbeitsbaum.
Eine „fremde" Aenderung schreibt ein ZWEITER Prozess, so wie im Vorfall.

  P   Positivkontrolle: ohne Schutz richtet das Vorfall-Skript den Schaden an
  S1  der Vorfall: Startsicherung, Probe liest neue Fassung, Ende copy2 alt
  S2  Probe sabotiert aus der Startsicherung, obwohl die Datei neu ist
  S3  Normalfall: alles wird zurueckgelegt, Exit 0, Journal weg
  S4  Schreibweg ``open(…, 'w')``
  S5  Schreibweg ``os.replace``
  S6  ``kill -9`` mitten in der Probe → naechster Lauf legt zurueck
  S7  ``kill -9`` + spaetere fremde Aenderung → bleibt, Exit 2
  S8  eine nie gesehene Datei im Repo ist kein Gegenstand (Exit 0)
  S9  Pfade ausserhalb der Wurzel sind nicht betroffen
  R   Regel: jeder ``tests/gegen_*.py`` schaltet den Schutz VOR seiner
      ersten Anweisung ein (AST), Ausnahmen nur benannt

``SCHREIBSCHUTZ_PFAD`` laedt das Modul aus einem anderen Verzeichnis,
``SCHREIBSCHUTZ_HARNESSE`` nimmt fuer R ein anderes Verzeichnis – beides fuer
``gegen_schreibschutz.py``, das sabotierte KOPIEN prueft.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIB = os.environ.get("SCHREIBSCHUTZ_PFAD") or str(ROOT / "tests" / "lib")
HARNESSE = pathlib.Path(os.environ.get("SCHREIBSCHUTZ_HARNESSE") or str(ROOT / "tests"))
if not (pathlib.Path(LIB) / "schreibschutz.py").is_file():
    print("ABBRUCH: schreibschutz.py fehlt in %s" % LIB)
    sys.exit(2)

ok = fail = 0


def pruefe(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text + ("  → " + str(zusatz) if zusatz else ""))


A, B = "eins\nANKER\nzwei\n", "eins\nANKER\nzwei\nvom Betreiber committet\n"

KOPF = textwrap.dedent('''
    import sys, os, pathlib, shutil
    sys.path.insert(0, {lib!r})
    WURZEL = pathlib.Path({wurzel!r}); ABLAGE = pathlib.Path({ablage!r})
    P = WURZEL / "d" / "a.txt"
    if {schutz!r}:
        import schreibschutz
        schreibschutz.aktivieren("harness_probe", root=WURZEL, journal_dir={journal!r})
    def fremd(text):
        # der Betreiber: ein ANDERER Prozess
        import subprocess
        subprocess.run([sys.executable, "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])",
            str(P), text], check=True)
''')


def szenario(rumpf, schutz=True, vorher=A, sb=None):
    """Fuehrt ``rumpf`` als eigenen Prozess aus. Rueckgabe (exit, inhalt, aus, sb)."""
    if sb is None:
        t = pathlib.Path(tempfile.mkdtemp(prefix="schreibschutz-"))
        (t / "wurzel" / "d").mkdir(parents=True)
        (t / "wurzel" / "d" / "a.txt").write_text(vorher, encoding="utf-8")
        (t / "wurzel" / "d" / "b.txt").write_text(A, encoding="utf-8")
        (t / "ablage").mkdir()
        (t / "aussen").mkdir()
        sb = t
    code = KOPF.format(lib=LIB, wurzel=str(sb / "wurzel"), ablage=str(sb / "ablage"),
                       schutz=schutz, journal=str(sb / "journal")) + textwrap.dedent(rumpf)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       timeout=60, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    inhalt = (sb / "wurzel" / "d" / "a.txt").read_text(encoding="utf-8")
    return r.returncode, inhalt, r.stdout + r.stderr, sb


VORFALL = '''
    shutil.copy2(P, ABLAGE / "a.txt")                 # Sicherung beim START
    fremd(%r)                                          # Commit waehrend des Laufs
    s = P.read_text()                                  # Probe liest NEUE Fassung
    P.write_text(s.replace("ANKER", "SABOTAGE"))
    P.write_text(s)                                    # Probe legt zurueck
    shutil.copy2(ABLAGE / "a.txt", P)                  # blindes zurueck() am ENDE
    sys.exit(0)
''' % B

aufraeumen = []

print("── P Positivkontrolle: ohne Schutz")
rc, inh, aus, sb = szenario(VORFALL, schutz=False); aufraeumen.append(sb)
if inh != A:
    print("ABBRUCH: das Vorfall-Skript richtet ohne Schutz keinen Schaden an (%r)" % inh)
    sys.exit(2)
pruefe("ohne Schutz wird die fremde Fassung ueberschrieben (Lage hergestellt)", rc == 0 and inh == A)

print("── S1 der Vorfall")
rc, inh, aus, sb = szenario(VORFALL); aufraeumen.append(sb)
pruefe("die fremde Fassung bleibt erhalten", inh == B, repr(inh))
pruefe("… und der Lauf endet mit Exit 2 (nicht deutbar), obwohl er 0 meldet", rc == 2, rc)
pruefe("… und nennt die Datei samt Grund (veraltete Sicherung)",
       "SCHREIBSCHUTZ" in aus and "a.txt" in aus and "veraltet" in aus, aus[-300:])

print("── S2 Sabotage aus der Startsicherung")
rc, inh, aus, sb = szenario('''
    orig = P.read_text()
    fremd(%r)
    P.write_text(orig.replace("ANKER", "SABOTAGE"))   # liest NICHT neu
    P.write_text(orig)
''' % B); aufraeumen.append(sb)
pruefe("Sabotage ueber eine fremd geaenderte Datei wird verweigert", inh == B, repr(inh))
pruefe("… Exit 2", rc == 2, rc)
pruefe("… Grund: von aussen geaendert", "von aussen" in aus, aus[-300:])

print("── S3 Normalfall")
rc, inh, aus, sb = szenario('''
    shutil.copy2(P, ABLAGE / "a.txt")
    s = P.read_text()
    P.write_text(s.replace("ANKER", "SABOTAGE"))
    P.write_text(s)
    shutil.copy2(ABLAGE / "a.txt", P)
''' ); aufraeumen.append(sb)
pruefe("Normalfall: Original steht, Exit 0", inh == A and rc == 0, (rc, inh))
pruefe("… und das Journal ist abgeraeumt", not (sb / "journal" / "harness_probe.json").exists())

print("── S4 Schreibweg open(…, 'w')")
rc, inh, aus, sb = szenario('''
    s = P.read_text()
    fremd(%r)
    with open(P, "w") as f:
        f.write(s)
''' % B); aufraeumen.append(sb)
pruefe("open-w ueber eine fremd geaenderte Datei wird verweigert", inh == B and rc == 2, (rc, inh))
rc, inh, aus, sb = szenario('''
    s = P.read_text()
    with open(P, "w") as f:
        f.write(s.replace("ANKER", "X"))
    with open(P, "w") as f:
        f.write(s)
''' ); aufraeumen.append(sb)
pruefe("open-w im Normalfall (eigene Sabotage, eigenes Zuruecklegen) geht durch",
       inh == A and rc == 0, (rc, inh, aus[-200:]))

print("── S5 Schreibweg os.replace")
rc, inh, aus, sb = szenario('''
    s = P.read_text()
    fremd(%r)
    t = ABLAGE / "neu.txt"; t.write_text(s)
    os.replace(t, P)
''' % B); aufraeumen.append(sb)
pruefe("os.replace ueber eine fremd geaenderte Datei wird verweigert", inh == B and rc == 2, (rc, inh))

print("── S6 kill -9 mitten in der Probe")
rc, inh, aus, sb = szenario('''
    shutil.copy2(P, ABLAGE / "a.txt")
    s = P.read_text()
    P.write_text(s.replace("ANKER", "SABOTAGE"))
    os._exit(9)
'''); aufraeumen.append(sb)
pruefe("Positivkontrolle: Sabotage liegt nach dem Abschuss noch", "SABOTAGE" in inh and rc == 9, (rc, inh))
rc, inh, aus, sb = szenario('''
    shutil.copy2(ABLAGE / "a.txt", P)                 # zurueck() beim Start
''', sb=sb)
pruefe("der naechste Lauf legt die eigene Sabotage zurueck", inh == A and rc == 0, (rc, inh, aus[-200:]))

print("── S7 kill -9 + spaetere fremde Aenderung")
rc, inh, aus, sb = szenario('''
    shutil.copy2(P, ABLAGE / "a.txt")
    s = P.read_text()
    P.write_text(s.replace("ANKER", "SABOTAGE"))
    os._exit(9)
'''); aufraeumen.append(sb)
(sb / "wurzel" / "d" / "a.txt").write_text(B, encoding="utf-8")
rc, inh, aus, sb = szenario('''
    shutil.copy2(ABLAGE / "a.txt", P)
''', sb=sb)
pruefe("die spaetere fremde Fassung bleibt, Exit 2", inh == B and rc == 2, (rc, inh))

print("── S8 nie gesehene Datei im Repo")
rc, inh, aus, sb = szenario('''
    (WURZEL / "d" / "b.txt").write_text("vom importierten Modul")
'''); aufraeumen.append(sb)
pruefe("eine nie gelesene Datei ist kein Gegenstand (Exit 0)", rc == 0, aus[-200:])

print("── S9 ausserhalb der Wurzel")
rc, inh, aus, sb = szenario('''
    q = WURZEL.parent / "aussen" / "x.txt"
    q.write_text("1"); q.read_text()
    import subprocess
    subprocess.run([sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('2')", str(q)])
    q.write_text("3")
'''); aufraeumen.append(sb)
pruefe("Dateien ausserhalb der Wurzel sind nicht betroffen", rc == 0, aus[-200:])

for t in aufraeumen:
    shutil.rmtree(t, ignore_errors=True)

# ── R: Regel ueber alle Harnesse ─────────────────────────────────────────────
print("── R jeder gegen_*.py schaltet den Schutz zuerst ein")
# Benannte Ausnahmen (Datei -> Grund). Leer heisst: keine.
AUSNAHMEN = {}


def ist_aktivierung(st):
    return (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Attribute)
            and st.value.func.attr == "aktivieren"
            and isinstance(st.value.func.value, ast.Name)
            and st.value.func.value.id == "schreibschutz")


def vorlauf_erlaubt(st):
    """Was VOR der Aktivierung stehen darf: Docstring, Importe, sys.path.insert."""
    if isinstance(st, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
        return True
    if (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Attribute) and st.value.func.attr == "insert"):
        return True
    return False


harnesse = sorted(HARNESSE.glob("gegen_*.py"))
pruefe("Positivkontrolle: es gibt nennenswert viele Harnesse", len(harnesse) >= 100, len(harnesse))
ohne, zu_spaet = [], []
for h in harnesse:
    if h.name in AUSNAHMEN:
        continue
    try:
        mod = ast.parse(h.read_text(encoding="utf-8"))
    except SyntaxError as e:
        ohne.append("%s (SyntaxError %s)" % (h.name, e))
        continue
    idx = next((i for i, st in enumerate(mod.body) if ist_aktivierung(st)), None)
    if idx is None:
        ohne.append(h.name)
    elif not all(vorlauf_erlaubt(st) for st in mod.body[:idx]):
        zu_spaet.append(h.name)
pruefe("jeder Harness schaltet den Schutz ein", not ohne, ", ".join(ohne[:8]) + (" …(%d)" % len(ohne) if len(ohne) > 8 else ""))
pruefe("… und zwar VOR seiner ersten eigenen Anweisung", not zu_spaet, ", ".join(zu_spaet[:8]))

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
