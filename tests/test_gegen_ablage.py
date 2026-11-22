#!/usr/bin/env python3
"""Waechter: Gegenproben raeumen ihre Sicherungsablage nach geordnetem Ende ab.

WARUM (2026-11-22): die ``gegen_*``-Harnesse sichern vor jeder Sabotage auf
Platte (``~/.gegen-<name>``) - richtig, ein abgeschossener Lauf muss seinen
Rueckstand beim naechsten Start zuruecknehmen koennen. Abgeraeumt wurde am
geordneten Ende aber meist nur die Laufmarke: 37 Ordner (54 MB) blieben im
Home liegen. Seitdem meldet jeder Harness ``gegen_ablage.abraeumen_bei_ende``
an (``tests/lib/gegen_ablage.py``).

Teil A misst die WIRKUNG des Helfers, jedes Szenario in einem eigenen
Prozess (atexit laeuft nur am echten Prozessende) mit Wegwerf-Wurzel
(``git init``) und Ablage in einem Wegwerf-Ordner unter dem Home.
Teil B prueft die REGEL am Syntaxbaum: jeder ``gegen_*.py`` mit einer
Verzeichnis-Ablage unter ``Path.home()`` ruft den Helfer auf Modulebene mit
DIESEM Namen auf (und mit seiner Laufmarke, wenn er eine hat) - VOR jedem
``atexit.register`` auf Modulebene, denn atexit laeuft rueckwaerts und das
Abraeumen muss nach dem Zuruecklegen kommen. Ein Vorkommen im Text zaehlt
nicht (ein Kommentar ist kein Aufruf).

Geltungsbereich: nur ``tests/gegen_*.py`` - nur die Harnesse sabotieren und
sichern. Ausgenommen sind Ablagen, die eine einzelne DATEI sind (Markendatei
im Home): die raeumen die Harnesse selbst per ``unlink`` ab, ein Ordner
entsteht dort nicht.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen (Positivkontrolle).
"""
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "tests" / "lib"
HARNESSE = ROOT / "tests"
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

ok = fail = 0


def pruefe(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text + (("  -> %s" % zusatz) if zusatz else ""))


def abbruch(grund):
    print("\nABBRUCH (Exit 2): " + grund)
    print("Ergebnis: %d OK, %d FAIL (nicht deutbar)" % (ok, fail))
    sys.exit(2)


# ═══ Teil A: Wirkung ════════════════════════════════════════════════════════

KOPF = textwrap.dedent("""\
    import os, sys, signal, atexit
    from pathlib import Path
    sys.path.insert(0, {lib!r})
    import gegen_ablage
    W = Path({wurzel!r}); A = Path({ablage!r}); M = A / "LAUF"
""")


def aufbau(basis: Path, name: str):
    """Frische Wurzel (git) mit zwei Dateien und leerer Ablage daneben."""
    fall = basis / name
    w, a = fall / "wurzel", fall / "ablage"
    (w / "a").mkdir(parents=True)
    (w / "b").mkdir()
    (w / "a" / "x.txt").write_text("inhalt x\n", encoding="utf-8")
    (w / "b" / "y.txt").write_text("inhalt y\n", encoding="utf-8")
    r = subprocess.run(["git", "init", "-q", str(w)], capture_output=True)
    if r.returncode != 0:
        abbruch("git init fehlgeschlagen: %s" % r.stderr.decode(errors="replace"))
    a.mkdir()
    return w, a


def lauf(w: Path, a: Path, rumpf: str):
    code = KOPF.format(lib=str(LIB), wurzel=str(w), ablage=str(a)) + textwrap.dedent(rumpf)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=60, env=UMG)


def teil_a(basis: Path):
    print("\n== Teil A: Wirkung des Helfers (je Szenario ein Prozess)")

    # Positivkontrolle der Messung: ohne Helfer bleibt die Ablage liegen.
    w, a = aufbau(basis, "ohne_helfer")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    r = lauf(w, a, "pass\n")
    if r.returncode != 0 or not a.exists():
        abbruch("Positivkontrolle: ohne Helfer muss die Ablage liegen bleiben (rc=%s, %s)"
                % (r.returncode, r.stderr.strip()[-300:]))
    print("  (Positivkontrolle: ohne Helfer bleibt die Ablage liegen)")

    w, a = aufbau(basis, "gleich")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    (a / "b__y.txt").write_bytes((w / "b" / "y.txt").read_bytes())
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\nsys.exit(3)\n")
    pruefe("alles gleich, keine Marke -> Ablage ist weg", not a.exists(), r.stderr.strip())
    pruefe("... und der Exit-Code des Harness bleibt unberuehrt (3)", r.returncode == 3, r.returncode)

    w, a = aufbau(basis, "marke")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    (a / "LAUF").write_text("1")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\n")
    pruefe("Laufmarke liegt -> Ablage bleibt", a.exists() and (a / "a__x.txt").exists())
    pruefe("... und der Grund steht auf stderr", "Laufmarke" in r.stderr, r.stderr.strip())

    # Marke AUSSERHALB der Ablage: hier haelt allein die Markenpruefung (in
    # der Ablage liegt sonst nur Gleiches, der Inhaltsvergleich sagte "weg").
    w, a = aufbau(basis, "marke_aussen")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    aussen = a.parent / "LAUF_aussen"
    aussen.write_text("1")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=A.parent / 'LAUF_aussen', wurzel=W)\n")
    pruefe("Laufmarke ausserhalb der Ablage liegt -> Ablage bleibt", a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "abweichung")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    (a / "b__y.txt").write_text("ALTSTAND y\n", encoding="utf-8")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\n")
    pruefe("eine Datei weicht ab -> Ablage bleibt", a.exists() and (a / "b__y.txt").exists())
    pruefe("... und stderr nennt die abweichende Datei", "b__y.txt" in r.stderr, r.stderr.strip())

    w, a = aufbau(basis, "dateiname")
    (a / "y.txt").write_bytes((w / "b" / "y.txt").read_bytes())
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\n")
    pruefe("nur der Dateiname abgelegt (p.name), Inhalt gleich -> weg", not a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "dateiname_abw")
    (a / "y.txt").write_text("ALTSTAND y\n", encoding="utf-8")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\n")
    pruefe("nur der Dateiname abgelegt, Inhalt anders -> bleibt", a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "endung")
    (a / "a__x.txt.bak").write_bytes((w / "a" / "x.txt").read_bytes())
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, wurzel=W)\n")
    pruefe("Sicherung mit .bak, Inhalt gleich -> weg", not a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "unterpfad")
    (a / "a").mkdir()
    (a / "a" / "x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, wurzel=W)\n")
    pruefe("Sicherung als Unterpfad (rel), Inhalt gleich -> weg", not a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "fremd")
    (a / "ergebnis.json").write_text("{}\n")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, wurzel=W)\n")
    pruefe("Datei ohne Gegenstueck im Arbeitsbaum -> bleibt", a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "verweis")
    os.symlink(w / "a" / "x.txt", a / "a__x.txt")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, wurzel=W)\n")
    pruefe("symbolischer Verweis in der Ablage -> bleibt", a.exists() and (w / "a" / "x.txt").exists(),
           r.stderr.strip())

    # Reihenfolge: das Harness-Muster (sichern, sabotieren, atexit-zurueck).
    sabotage = """\
        (A / "a__x.txt").write_bytes((W / "a" / "x.txt").read_bytes())
        M.write_text("1")
        (W / "a" / "x.txt").write_text("SABOTIERT\\n")
        def zurueck():
            (W / "a" / "x.txt").write_bytes((A / "a__x.txt").read_bytes())
            M.unlink()
    """
    w, a = aufbau(basis, "reihenfolge_richtig")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\n"
             + textwrap.dedent(sabotage) + "atexit.register(zurueck)\n")
    pruefe("Helfer VOR dem Zuruecklegen angemeldet -> Baum heil, Ablage weg",
           not a.exists() and (w / "a" / "x.txt").read_text() == "inhalt x\n", r.stderr.strip())

    w, a = aufbau(basis, "reihenfolge_falsch")
    r = lauf(w, a, textwrap.dedent(sabotage) + "atexit.register(zurueck)\n"
             "gegen_ablage.abraeumen_bei_ende(A, wurzel=W)\n")
    pruefe("Helfer NACH dem Zuruecklegen angemeldet -> Ablage bleibt (sah den sabotierten Baum)",
           a.exists() and (a / "a__x.txt").exists(), r.stderr.strip())

    w, a = aufbau(basis, "kill9")
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(A, marke=M, wurzel=W)\n"
             + textwrap.dedent(sabotage) + "atexit.register(zurueck)\n"
             "os.kill(os.getpid(), signal.SIGKILL)\n")
    pruefe("kill -9 mitten im Lauf -> Ablage und Marke bleiben", a.exists() and (a / "LAUF").exists(),
           r.returncode)

    # Harte Grenzen. Die Ablage liegt dabei immer in eigenem Wegwerf-Material.
    w, a = aufbau(basis, "im_repo")
    innen = w / "sicherung"
    innen.mkdir()
    (innen / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(W / 'sicherung', wurzel=W)\n")
    pruefe("Ablage innerhalb des Arbeitsbaums -> bleibt", innen.exists(), r.stderr.strip())

    w, a = aufbau(basis, "ausserhalb")
    draussen = Path(tempfile.mkdtemp(prefix="waechter-gegen-ablage-"))
    try:
        if Path.home().resolve() in draussen.resolve().parents:
            print("  (Hinweis: das Temp-Verzeichnis liegt im Home - Szenario 'ausserhalb' nicht messbar)")
        else:
            (draussen / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
            r = lauf(w, a, "gegen_ablage.abraeumen_bei_ende(Path(%r), wurzel=W)\n" % str(draussen))
            pruefe("Ablage ausserhalb des Home -> bleibt", draussen.exists(), r.stderr.strip())
    finally:
        shutil.rmtree(draussen, ignore_errors=True)

    # Das Home selbst wird nie geloescht - hier NUR die reine Pruefung, damit
    # ein kaputter Helfer an dieser Stelle nichts anrichten kann.
    sys.path.insert(0, str(LIB))
    import gegen_ablage
    pruefe("das Home selbst ist gesperrt", bool(gegen_ablage._gesperrt(Path.home(), w)))
    pruefe("ein Vorfahr des Arbeitsbaums ist gesperrt", bool(gegen_ablage._gesperrt(w.parent, w)))


# ═══ Teil B: Regel ══════════════════════════════════════════════════════════

def _hat_home(knoten):
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "home"
               for c in ast.walk(knoten))


def _ist_verzeichnis(baum, name):
    for c in ast.walk(baum):
        if (isinstance(c, ast.BinOp) and isinstance(c.op, ast.Div)
                and isinstance(c.left, ast.Name) and c.left.id == name):
            return True
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("mkdir", "iterdir", "glob", "rglob")
                and isinstance(c.func.value, ast.Name) and c.func.value.id == name):
            return True
    return False


def _ist_helfer_aufruf(st):
    if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)):
        return None
    f = st.value.func
    name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
    return st.value if name == "abraeumen_bei_ende" else None


def _registriert_atexit(st):
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "register"
               and isinstance(c.func.value, ast.Name) and c.func.value.id == "atexit"
               for c in ast.walk(st))


def befunde(quelle: str):
    """(erfasste Ablagen, Befunde) fuer eine Quelle."""
    baum = ast.parse(quelle)
    ablagen = []
    for st in baum.body:
        if (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)
                and not isinstance(st.value, ast.Call) and _hat_home(st.value)
                and _ist_verzeichnis(baum, st.targets[0].id)):
            ablagen.append((st.targets[0].id, st.lineno))
    aus = []
    for name, zeile in ablagen:
        marken = [st.targets[0].id for st in baum.body
                  if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)
                  and isinstance(st.value, ast.BinOp) and isinstance(st.value.left, ast.Name)
                  and st.value.left.id == name and st.targets[0].id.upper().startswith(("MARKE", "LAUF"))]
        aufrufe = [(st.lineno, c) for st in baum.body for c in [_ist_helfer_aufruf(st)]
                   if c is not None and c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == name]
        if not aufrufe:
            aus.append("%s: kein abraeumen_bei_ende(%s) auf Modulebene" % (name, name))
            continue
        z, aufruf = aufrufe[0]
        frueh = [st.lineno for st in baum.body if _registriert_atexit(st) and st.lineno < z]
        if frueh:
            aus.append("%s: Aufruf (Zeile %d) steht HINTER atexit.register (Zeile %d)" % (name, z, frueh[0]))
        if z < zeile:
            aus.append("%s: Aufruf (Zeile %d) steht vor der Zuweisung (Zeile %d)" % (name, z, zeile))
        if marken:
            kw = {k.arg: k.value for k in aufruf.keywords}
            m = kw.get("marke")
            if not (isinstance(m, ast.Name) and m.id in marken):
                aus.append("%s: Laufmarke %s nicht uebergeben" % (name, marken[0]))
    return [n for n, _ in ablagen], aus


PROBEN = {
    "schlecht": ('from pathlib import Path\nABL = Path.home() / ".x"\nMARKE = ABL / "LAUF"\n', 1),
    "gut": ('from pathlib import Path\nimport atexit, gegen_ablage\nABL = Path.home() / ".x"\n'
            'MARKE = ABL / "LAUF"\ngegen_ablage.abraeumen_bei_ende(ABL, marke=MARKE)\n'
            'atexit.register(print)\n', 0),
    "nur Markendatei": ('from pathlib import Path\nMARKE = Path.home() / ".x.laeuft"\n'
                        'MARKE.write_text("1")\n', 0),
    "Aufruf hinter atexit": ('from pathlib import Path\nimport atexit, gegen_ablage\n'
                             'ABL = Path.home() / ".x"\nABL.mkdir()\natexit.register(print)\n'
                             'gegen_ablage.abraeumen_bei_ende(ABL)\n', 1),
    "Aufruf mit fremdem Namen": ('from pathlib import Path\nimport gegen_ablage\nABL = Path.home() / ".x"\n'
                                 'X = ABL / "a"\ngegen_ablage.abraeumen_bei_ende(X)\n', 1),
    "Marke nicht uebergeben": ('from pathlib import Path\nimport gegen_ablage\nABL = Path.home() / ".x"\n'
                               'MARKE = ABL / "LAUF"\ngegen_ablage.abraeumen_bei_ende(ABL)\n', 1),
    "nur im Kommentar und Docstring": ('"""gegen_ablage.abraeumen_bei_ende(ABL)"""\nfrom pathlib import Path\n'
                                       'ABL = Path.home() / ".x"\nABL.mkdir()\n'
                                       '# gegen_ablage.abraeumen_bei_ende(ABL)\n', 1),
    "Aufruf in einer Funktion": ('from pathlib import Path\nimport gegen_ablage\nABL = Path.home() / ".x"\n'
                                 'ABL.mkdir()\ndef main():\n    gegen_ablage.abraeumen_bei_ende(ABL)\n', 1),
}


def teil_b():
    print("\n== Teil B: Regel ueber alle tests/gegen_*.py")
    for name, (quelle, soll) in PROBEN.items():
        try:
            _, aus = befunde(quelle)
        except Exception as exc:  # noqa: BLE001
            abbruch("Positivkontrolle '%s' wirft: %r" % (name, exc))
        if len(aus) != soll:
            abbruch("Positivkontrolle '%s': %d Befund(e) statt %d %s" % (name, len(aus), soll, aus))
    print("  (Positivkontrolle: %d synthetische Quellen richtig beurteilt)" % len(PROBEN))

    erfasst, schlecht = 0, []
    for h in sorted(HARNESSE.glob("gegen_*.py")):
        try:
            namen, aus = befunde(h.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            schlecht.append("%s: SyntaxError %s" % (h.name, exc))
            continue
        erfasst += bool(namen)
        schlecht += ["%s: %s" % (h.name, a) for a in aus]
    if erfasst == 0:
        abbruch("kein einziger Harness mit Home-Ablage erfasst - die Erkennung ist blind")
    print("  (%d Harnesse mit Verzeichnis-Ablage im Home erfasst)" % erfasst)
    pruefe("jeder Harness mit Home-Ablage raeumt sie per Helfer ab, vor seinem atexit, mit Marke",
           not schlecht, "; ".join(schlecht[:6]) + (" ...(%d)" % len(schlecht) if len(schlecht) > 6 else ""))


def main():
    if shutil.which("git") is None:
        abbruch("git fehlt")
    basis = Path(tempfile.mkdtemp(prefix=".waechter-gegen-ablage-", dir=Path.home()))
    try:
        teil_a(basis)
    finally:
        shutil.rmtree(basis, ignore_errors=True)
    teil_b()
    print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
