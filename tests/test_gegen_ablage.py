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

Teil C (2026-11-22) dasselbe fuer die JS-Harnesse ``tests/gegen_*.js``: die
Wirkung von ``tests/lib/gegen_ablage.js`` (ruft beim Prozessende die Regel
dieser Python-Datei) je Szenario in einem Node-Prozess, und die Regel am
Syntaxbaum ueber ``tests/lib/gegen_ablage_regel.js`` (acorn). In Node laufen
exit-Handler in ANMELDE-Reihenfolge - ein spaeter angemeldetes Zuruecklegen
ist dort der Befund.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen (Positivkontrolle).
"""
import ast
import json
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
NODE = shutil.which("node")

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


# ═══ Teil C: JS-Harnesse (tests/lib/gegen_ablage.js) ══════════════════════

KOPF_JS = ("const fs = require('fs'), path = require('path');\n"
           "const gegenAblage = require({helfer});\n"
           "const W = {wurzel}, A = {ablage}, M = path.join(A, 'LAUF');\n")


def lauf_js(w: Path, a: Path, rumpf: str):
    code = KOPF_JS.format(helfer=json.dumps(str(LIB / "gegen_ablage.js")), wurzel=json.dumps(str(w)),
                          ablage=json.dumps(str(a))) + textwrap.dedent(rumpf)
    return subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=60, env=UMG)


def teil_c(basis: Path):
    print("\n== Teil C: JS-Helfer (je Szenario ein Node-Prozess) und Regel ueber tests/gegen_*.js")
    w, a = aufbau(basis, "js_ohne_helfer")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    r = lauf_js(w, a, "process.exit(0);\n")
    if r.returncode != 0 or not a.exists():
        abbruch("Positivkontrolle JS: ohne Helfer muss die Ablage liegen bleiben (rc=%s, %s)"
                % (r.returncode, r.stderr.strip()[-300:]))

    aufruf = "gegenAblage.abraeumenBeimEnde(A, { marke: M, wurzel: W });\n"
    w, a = aufbau(basis, "js_gleich")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    (a / "b__y.txt").write_bytes((w / "b" / "y.txt").read_bytes())
    r = lauf_js(w, a, aufruf + "process.exit(1);\n")
    pruefe("JS: alles gleich, keine Marke -> Ablage ist weg", not a.exists(), r.stderr.strip())
    pruefe("JS: ... und der Exit-Code des Harness bleibt unberuehrt (1 = Befund)", r.returncode == 1, r.returncode)

    w, a = aufbau(basis, "js_marke")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    (a / "LAUF").write_text("1")
    r = lauf_js(w, a, aufruf)
    pruefe("JS: Laufmarke liegt -> Ablage bleibt, Grund auf stderr",
           a.exists() and "Laufmarke" in r.stderr, r.stderr.strip())

    # Marke AUSSERHALB der Ablage: nur hier haelt allein die Markenpruefung -
    # ein Helfer, der die Marke nicht weiterreicht, faellt sonst nicht auf.
    w, a = aufbau(basis, "js_marke_aussen")
    (a / "a__x.txt").write_bytes((w / "a" / "x.txt").read_bytes())
    (a.parent / "LAUF_aussen").write_text("1")
    r = lauf_js(w, a, "gegenAblage.abraeumenBeimEnde(A, { marke: path.join(A, '..', 'LAUF_aussen'), wurzel: W });\n")
    pruefe("JS: Laufmarke ausserhalb der Ablage liegt -> Ablage bleibt", a.exists(), r.stderr.strip())

    w, a = aufbau(basis, "js_abweichung")
    (a / "a__x.txt").write_text("ALTSTAND x\n", encoding="utf-8")
    r = lauf_js(w, a, aufruf)
    pruefe("JS: eine Datei weicht ab -> Ablage bleibt", a.exists() and "a__x.txt" in r.stderr, r.stderr.strip())

    # Das Muster der Harnesse: sichern, sabotieren, im finally zuruecklegen, exit.
    w, a = aufbau(basis, "js_muster")
    r = lauf_js(w, a, aufruf + """\
        const x = path.join(W, 'a', 'x.txt');
        fs.copyFileSync(x, path.join(A, 'a__x.txt')); fs.writeFileSync(M, '1');
        try { fs.writeFileSync(x, 'SABOTIERT\\n'); }
        finally { fs.copyFileSync(path.join(A, 'a__x.txt'), x); fs.unlinkSync(M); }
        process.exit(0);
    """)
    pruefe("JS: Harness-Muster (finally legt zurueck) -> Baum heil, Ablage weg",
           not a.exists() and (w / "a" / "x.txt").read_text() == "inhalt x\n", r.stderr.strip())

    w, a = aufbau(basis, "js_exit_handler_spaet")
    r = lauf_js(w, a, aufruf + """\
        const x = path.join(W, 'a', 'x.txt');
        fs.copyFileSync(x, path.join(A, 'a__x.txt')); fs.writeFileSync(M, '1');
        fs.writeFileSync(x, 'SABOTIERT\\n');
        process.on('exit', () => { fs.copyFileSync(path.join(A, 'a__x.txt'), x); fs.unlinkSync(M); });
    """)
    pruefe("JS: Zuruecklegen als exit-Handler NACH dem Helfer -> Ablage bleibt (sah den sabotierten Baum)",
           a.exists() and (a / "a__x.txt").exists(), r.stderr.strip())

    w, a = aufbau(basis, "js_kill")
    r = lauf_js(w, a, aufruf + """\
        fs.copyFileSync(path.join(W, 'a', 'x.txt'), path.join(A, 'a__x.txt')); fs.writeFileSync(M, '1');
        process.kill(process.pid, 'SIGKILL');
    """)
    pruefe("JS: Abschuss per Signal -> Ablage und Marke bleiben", a.exists() and (a / "LAUF").exists(),
           r.returncode)

    # Regel: erst an synthetischen Quellen, dann am Bestand.
    regel = LIB / "gegen_ablage_regel.js"
    kopf = "const fs = require('fs'), os = require('os'), path = require('path');\n" \
           "const S = path.join(os.homedir(), '.x');\n"
    proben_js = {
        "ohne Aufruf": (kopf + "const MARKE = path.join(S, 'LAUF');\nfs.mkdirSync(S);\n", 1),
        "gut": (kopf + "const MARKE = path.join(S, 'LAUF');\n"
                "require('./lib/gegen_ablage').abraeumenBeimEnde(S, { marke: MARKE });\n", 0),
        "Marke fehlt": (kopf + "const MARKE = path.join(S, 'LAUF');\n"
                        "require('./lib/gegen_ablage').abraeumenBeimEnde(S);\n", 1),
        "nur im Kommentar": (kopf + "fs.mkdirSync(S);\n// x.abraeumenBeimEnde(S);\n", 1),
        "in einer Funktion": (kopf + "fs.mkdirSync(S);\nfunction f() { g.abraeumenBeimEnde(S); }\n", 1),
        "exit-Handler dahinter": (kopf + "fs.mkdirSync(S);\ng.abraeumenBeimEnde(S);\n"
                                  "process.on('exit', () => {});\n", 1),
        "keine Home-Ablage": ("const fs = require('fs');\nconst S = '/tmp/x';\nfs.mkdirSync(S);\n", 0),
    }
    pdir = basis / "regelproben"
    pdir.mkdir()
    for i, (name, (quelle, _)) in enumerate(proben_js.items()):
        (pdir / ("p%d.js" % i)).write_text(quelle, encoding="utf-8")
    r = subprocess.run([NODE, str(regel)] + [str(pdir / ("p%d.js" % i)) for i in range(len(proben_js))],
                       capture_output=True, text=True, timeout=60)
    try:
        erg = json.loads(r.stdout)
    except ValueError:
        abbruch("Regel-Werkzeug lieferte nichts Lesbares (rc=%s): %s" % (r.returncode, r.stderr.strip()[-300:]))
    for i, (name, (_, soll)) in enumerate(proben_js.items()):
        ist = len(erg[str(pdir / ("p%d.js" % i))]["befunde"])
        if ist != soll:
            abbruch("Positivkontrolle JS '%s': %d Befund(e) statt %d %s"
                    % (name, ist, soll, erg[str(pdir / ("p%d.js" % i))]["befunde"]))
    print("  (Positivkontrolle: %d synthetische JS-Quellen richtig beurteilt)" % len(proben_js))
    harnesse = sorted(HARNESSE.glob("gegen_*.js"))
    if not harnesse:
        abbruch("keine tests/gegen_*.js gefunden")
    r = subprocess.run([NODE, str(regel)] + [str(h) for h in harnesse], capture_output=True, text=True, timeout=60)
    try:
        erg = json.loads(r.stdout)
    except ValueError:
        abbruch("Regel-Werkzeug am Bestand unlesbar (rc=%s): %s" % (r.returncode, r.stderr.strip()[-300:]))
    erfasst = sum(1 for v in erg.values() if v["ablagen"])
    if erfasst == 0:
        abbruch("kein JS-Harness mit Home-Ablage erfasst - die Erkennung ist blind")
    schlecht = ["%s: %s" % (Path(k).name, b) for k, v in erg.items() for b in v["befunde"]]
    print("  (%d JS-Harnesse mit Verzeichnis-Ablage im Home erfasst)" % erfasst)
    pruefe("jeder JS-Harness mit Home-Ablage raeumt sie per Helfer ab, mit Marke, ohne spaeten exit-Handler",
           not schlecht, "; ".join(schlecht[:6]))


def main():
    if shutil.which("git") is None:
        abbruch("git fehlt")
    if NODE is None:
        abbruch("node fehlt - Teil C (JS-Harnesse) misst nichts")
    basis = Path(tempfile.mkdtemp(prefix=".waechter-gegen-ablage-", dir=Path.home()))
    try:
        teil_a(basis)
        teil_b()
        teil_c(basis)
    finally:
        shutil.rmtree(basis, ignore_errors=True)
    print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
