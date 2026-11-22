#!/usr/bin/env python3
"""Waechter: die Waechter bleiben schnell - linearer Quelltext-Zugriff, laengste zuerst.

WARUM (2026-11-22): die langsamsten Python-Waechter verbrachten ihre Zeit mit
Zeilenzaehlen, nicht mit Pruefen. ``ast.get_source_segment`` zerlegt bei
JEDEM Aufruf die Quelle neu (``test_anhang_bild_mime``: 77,7 s, mit Index
1,1 s), und Kommentar-Entferner summierten je Kommentar alle Zeilen davor
(``test_benutzer_pfade``: 60,3 s -> 4,6 s). Jede Gegenprobe startet ihren
Waechter je Probe neu und zahlt das vielfach. Und der Sammellauf startete
alphabetisch - der laengste Waechter konnte als letzter beginnen.

Teil A misst den Helfer ``tests/lib/quell_ausschnitt.py``: ``segment`` ist
Zeichen fuer Zeichen ``ast.get_source_segment`` (Stichprobe aus main.py plus
Faelle mit \\r, \\f, Trennzeichen in Zeichenketten, Mehrbyte-Zeichen,
``padded``), zerlegt je Quelle nur EINMAL, und ``ZeilenVersatz`` ist die
Praefixsumme mit Slice-Bedeutung.

Teil B prueft die REGEL am Syntaxbaum, in allen ``tests/**/*.py``: kein
Zugriff auf ``.get_source_segment`` (ausser im Helfer), keine Praefixsumme
``sum(len(z) ... for z in zeilen[:k])``, und wer ``quell_ausschnitt``
benutzt, importiert es auch. Ein Vorkommen im Text zaehlt nicht.

Teil C misst ``tests/ci_lauf.py`` an einem Wegwerf-Testordner: Start nach
gespeicherter Laufzeit (laengste zuerst, unbekannte davor), Speichern als
Mischung, kaputte Datei = alphabetisch, Ausgabe nach Namen.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen (Positivkontrolle).
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
HELFER = TESTS / "lib" / "quell_ausschnitt.py"
sys.path.insert(0, str(TESTS / "lib"))

ok = fail = 0


def pruefe(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text + (("  -> %s" % (zusatz,)) if zusatz else ""))


def abbruch(grund):
    print("\nABBRUCH (Exit 2): " + grund)
    print("Ergebnis: %d OK, %d FAIL (nicht deutbar)" % (ok, fail))
    sys.exit(2)


def modul_laden(pfad: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if not HELFER.is_file():
    abbruch(f"{HELFER.relative_to(ROOT)} fehlt")
qa = modul_laden(HELFER, "quell_ausschnitt_pruefling")

# ═══ Teil A: der Helfer ════════════════════════════════════════════════════
print("Teil A: quell_ausschnitt")

MAIN = ROOT / "backend" / "main.py"
if not MAIN.is_file():
    abbruch("backend/main.py fehlt - keine grosse Quelle zum Vergleich")
gross = MAIN.read_text(encoding="utf-8")
knoten_gross = [n for n in ast.walk(ast.parse(gross)) if hasattr(n, "end_lineno")]
# Stichprobe: gleichmaessig ueber die Datei verteilt, getrennt nach ein- und
# mehrzeiligen Knoten. Alle Knoten mit der Bibliothek zu vergleichen waere
# genau das Quadrat, das hier wegfallen soll (je Aufruf ~40 ms auf main.py).
_ein = [n for n in knoten_gross if n.end_lineno == n.lineno]
_mehr = [n for n in knoten_gross if n.end_lineno > n.lineno]
einzeilig = _ein[::max(1, len(_ein) // 40)]
mehrzeilig = _mehr[::max(1, len(_mehr) // 20)]
stichprobe = einzeilig + mehrzeilig
# Positivkontrolle: genug Knoten beider Arten - sonst waere der Vergleich
# eines Zweigs trivial wahr.
if len(einzeilig) < 30 or len(mehrzeilig) < 15:
    abbruch(f"Stichprobe zu klein ({len(einzeilig)} ein-, {len(mehrzeilig)} mehrzeilig)")

# padded wirkt nur bei mehrzeiligen Knoten - einzeilige nur einmal vergleichen
abweichend = [n for n in stichprobe
              for pad in ((False, True) if n in mehrzeilig else (False,))
              if qa.segment(gross, n, padded=pad) != ast.get_source_segment(gross, n, padded=pad)]
pruefe(f"main.py: segment == ast.get_source_segment ({len(einzeilig)} ein-, "
       f"{len(mehrzeilig)} mehrzeilige Knoten, mit/ohne padded)", not abweichend,
       [(n.lineno, type(n).__name__) for n in abweichend[:3]])

# Eine kleinere echte Datei VOLLSTAENDIG (jeder Knoten, beide Varianten).
KLEIN = TESTS / "lib" / "gegen_ablage.py"
if not KLEIN.is_file():
    abbruch(f"{KLEIN.relative_to(ROOT)} fehlt")
klein = KLEIN.read_text(encoding="utf-8")
kn_klein = [n for n in ast.walk(ast.parse(klein)) if hasattr(n, "end_lineno")]
falsch = [n for n in kn_klein for pad in (False, True)
          if qa.segment(klein, n, padded=pad) != ast.get_source_segment(klein, n, padded=pad)]
pruefe(f"{KLEIN.name}: gleich fuer alle {len(kn_klein)} Knoten", len(kn_klein) > 200 and not falsch,
       [(n.lineno, type(n).__name__) for n in falsch[:3]])

# Grenzfaelle: \r\n und \r allein trennen Zeilen, \f nicht; \x1c und \u2028
# in Zeichenketten trennt str.splitlines, der Parser nicht; Mehrbyte-Zeichen
# vor dem Knoten verschieben die Byte-Spalte; Tabulator und \f im Polster.
SONDER = {
    "CRLF": "a = 1\r\nb = (2 +\r\n     3)\r\n",
    "CR allein": "a = 1\rb = (2 +\r     3)\r",
    "Seitenvorschub": "\fx = 1\n\fdef f():\n\f    return (1 +\f\n            2)\n",
    "Trenner in Zeichenketten": 's = "a\x1cb\u2028c\x0bd"\nt = (s +\n     s)\n',
    "Mehrbyte": "ä = 'öü'; ß = ('€' +\n  '𝄞')\nprint(ä, ß)\n",
    "Tabulator": "if 1:\n\tx = (1 +\n\t     2)\n",
}
for titel, quelle in SONDER.items():
    kn = [n for n in ast.walk(ast.parse(quelle)) if hasattr(n, "end_lineno")]
    falsch = [n for n in kn for pad in (False, True)
              if qa.segment(quelle, n, padded=pad) != ast.get_source_segment(quelle, n, padded=pad)]
    pruefe(f"Grenzfall {titel}: gleich fuer alle {len(kn)} Knoten", kn and not falsch,
           [(n.lineno, n.col_offset, type(n).__name__) for n in falsch[:3]])

# Knoten ohne Position: wie die Bibliothek None, kein Absturz
ohne = ast.Name(id="x")
halb = ast.Name(id="x", lineno=1, col_offset=0, end_lineno=None, end_col_offset=None)
pruefe("Knoten ohne Position -> None wie die Bibliothek",
       qa.segment("x\n", ohne) is None and qa.segment("x\n", halb) is None)

# Je Quelle nur EINMAL zerlegen - am Zaehler gemessen, nicht an der Uhr.
zaehler = {"n": 0}
_echt = qa._zerlegen


def _gezaehlt(quelle):
    zaehler["n"] += 1
    return _echt(quelle)


qa._zerlegen = _gezaehlt
qa._ablage.clear()
try:
    for n in stichprobe * 5:
        qa.segment(gross, n)
    kopie = "".join([gross[:10], gross[10:]])   # gleicher Text, anderes Objekt
    qa.segment(kopie, stichprobe[0])
finally:
    qa._zerlegen = _echt
pruefe(f"main.py: {len(stichprobe) * 5 + 1} Ausschnitte, die Quelle wird 1x zerlegt",
       zaehler["n"] == 1, zaehler["n"])

# ZeilenVersatz == Praefixsumme mit Slice-Bedeutung (auch k < 0, k > n)
for zeilen, zusatz in ((["ab\n", "c\n", "\n", "def"], 0), (["ab", "", "cde"], 1), ([], 0), ([], 1)):
    vs = qa.ZeilenVersatz(zeilen, zusatz=zusatz)
    bereich = range(-len(zeilen) - 2, len(zeilen) + 3)
    falsch = [k for k in bereich if vs(k) != sum(len(z) + zusatz for z in zeilen[:k])]
    pruefe(f"ZeilenVersatz({len(zeilen)} Zeilen, zusatz={zusatz}) == sum(...[:k]) fuer k in "
           f"{bereich.start}..{bereich.stop - 1}", not falsch, falsch[:5])

# ═══ Teil B: die Regel ═════════════════════════════════════════════════════
print("\nTeil B: Regel in tests/**/*.py")


def _ist_praefixsumme(k) -> bool:
    """``sum(<..len(..)..> for z in X[:k])`` - je Aufruf ueber alle Zeilen davor."""
    if not (isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == "sum"
            and k.args and isinstance(k.args[0], (ast.GeneratorExp, ast.ListComp))):
        return False
    gen = k.args[0]
    mit_len = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "len"
                  for c in ast.walk(gen.elt))
    vorne = any(isinstance(g.iter, ast.Subscript) and isinstance(g.iter.slice, ast.Slice)
                and g.iter.slice.lower is None and g.iter.slice.upper is not None
                and g.iter.slice.step is None for g in gen.generators)
    return mit_len and vorne


def befunde(quelle: str) -> list:
    """(Zeile, Art) fuer jeden Verstoss in einer Quelle."""
    baum = ast.parse(quelle)
    aus = []
    importiert = False
    benutzt = None
    for k in ast.walk(baum):
        if isinstance(k, ast.Attribute) and k.attr == "get_source_segment":
            aus.append((k.lineno, "get_source_segment direkt"))
        elif isinstance(k, ast.ImportFrom) and k.module == "ast" and \
                any(a.name == "get_source_segment" for a in k.names):
            aus.append((k.lineno, "from ast import get_source_segment"))
        elif _ist_praefixsumme(k):
            aus.append((k.lineno, "Praefixsumme sum(len(..) for .. in X[:k])"))
        if isinstance(k, ast.Import) and any(a.name == "quell_ausschnitt" and a.asname is None
                                             for a in k.names):
            importiert = True
        if isinstance(k, ast.Name) and k.id == "quell_ausschnitt" and benutzt is None:
            benutzt = k.lineno
    if benutzt is not None and not importiert:
        aus.append((benutzt, "quell_ausschnitt benutzt, aber nicht importiert"))
    return aus


# Positivkontrollen: jede Form muss genau EINMAL anschlagen, die harmlosen nie.
PROBEN = {
    "ast.get_source_segment(q, n)": "import ast\nx = ast.get_source_segment(q, n)\n",
    "Alias _a.get_source_segment": "import ast as _a\nx = _a.get_source_segment(q, n)\n",
    "nur referenziert": "import ast\nf = ast.get_source_segment\n",
    "from ast import": "from ast import get_source_segment\n",
    "Praefixsumme ohne Zusatz": "s = sum(len(z) for z in zeilen[:k - 1]) + 3\n",
    "Praefixsumme mit Zusatz": "s = sum(len(z) + 1 for z in zeilen[:zs - 1])\n",
    "fehlender Import": "x = quell_ausschnitt.segment(q, n)\n",
}
HARMLOS = ("import quell_ausschnitt\nx = quell_ausschnitt.segment(q, n)\n"
           "# ast.get_source_segment(q, n) im Kommentar\n"
           "t = 'ast.get_source_segment(q, n)'\n"
           "s = sum(len(z) for z in zeilen)\n"
           "r = sum(len(z) for z in zeilen[2:])\n"
           "u = sum(z for z in zahlen[:3])\n")
for titel, quelle in PROBEN.items():
    gef = befunde(quelle)
    if len(gef) != 1:
        abbruch(f"Positivkontrolle '{titel}': {len(gef)} statt 1 Befund {gef}")
if befunde(HARMLOS):
    abbruch(f"Positivkontrolle harmlos: {befunde(HARMLOS)}")
pruefe(f"Erkennung: {len(PROBEN)} Formen schlagen an, Kommentar/Text/Summe ohne Slice nicht", True)

# Ausgenommen: der Helfer selbst und DIESER Waechter - beide brauchen das
# Original als Massstab (Vergleich in Teil A, Positivkontrollen in Teil B).
AUSGENOMMEN = {HELFER.resolve(), Path(__file__).resolve()}
dateien = sorted(p for p in TESTS.rglob("*.py")
                 if "__pycache__" not in p.parts and p.resolve() not in AUSGENOMMEN)
namen = {p.relative_to(TESTS).as_posix() for p in dateien}
# Positivkontrolle: der Bestand, an dem der Fehler gemessen wurde, ist dabei.
fehlt = {"test_anhang_bild_mime.py", "test_benutzer_pfade.py", "lib/sabotage_anker.py"} - namen
if fehlt:
    abbruch(f"Geltungsbereich verfehlt: {sorted(fehlt)}")
verstoesse = []
unlesbar = []
# Vorfilter: ohne einen der drei Namen im Text KANN der Baum keinen Verstoss
# tragen (Attribut, Aufruf und Name brauchen den Bezeichner woertlich). Er
# entscheidet nichts, er spart nur das Parsen von ~800 Dateien; geurteilt
# wird weiter am Syntaxbaum.
_SPUR = ("get_source_segment", "sum", "quell_ausschnitt")
geparst = 0
for p in dateien:
    try:
        quelle = p.read_text(encoding="utf-8")
        if not any(s in quelle for s in _SPUR):
            continue
        geparst += 1
        verstoesse += [(p.relative_to(ROOT).as_posix(), z, art) for z, art in befunde(quelle)]
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        unlesbar.append((p.relative_to(ROOT).as_posix(), type(exc).__name__))
# Positivkontrolle des Vorfilters: die Dateien, die den Helfer benutzen,
# muessen durchkommen - sonst prueft die Regel nichts.
if geparst < 70:
    abbruch(f"Vorfilter laesst nur {geparst} Dateien durch")
pruefe(f"{len(dateien)} Dateien ({geparst} mit Spur geparst): kein get_source_segment, "
       "keine Praefixsumme, Import vorhanden",
       not verstoesse, verstoesse[:6])
pruefe("alle geparsten Dateien am Syntaxbaum lesbar (sonst wuerde eine still uebersprungen)",
       not unlesbar, unlesbar[:5])

# ═══ Teil C: Sammellauf startet die laengsten zuerst ═══════════════════════
print("\nTeil C: ci_lauf.py - Reihenfolge nach Laufzeit")

CI = TESTS / "ci_lauf.py"
ci = modul_laden(CI, "ci_lauf_pruefling")
for name in ("main", "lauf", "kandidaten"):
    if not hasattr(ci, name):
        abbruch(f"ci_lauf.{name} fehlt - Teil C misst nichts")

tmp = Path(tempfile.mkdtemp(prefix="waechter-tempo-"))
alt_env = os.environ.get("JARVIS_CI_DAUERN")
alt = (ci.TESTS, ci.WURZEL, ci.AUSNAHMEN, sys.argv)
try:
    prot = tmp / "start.txt"
    probe = tmp / "tests"
    probe.mkdir()
    for n in "abcd":
        (probe / f"test_{n}.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            f"with open({str(prot)!r}, 'a') as f:\n    f.write('test_{n}.py\\n')\n"
            "print('Ergebnis: 1 OK, 0 FAIL')\nsys.exit(0)\n", encoding="utf-8")
    ci.TESTS, ci.WURZEL, ci.AUSNAHMEN = probe, tmp, tmp / "keine_ausnahmen.txt"
    dauern = tmp / "dauern.json"
    os.environ["JARVIS_CI_DAUERN"] = str(dauern)

    def sammellauf():
        prot.write_text("")
        sys.argv = ["ci_lauf.py", "--parallel", "1"]
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer), contextlib.redirect_stderr(puffer):
            try:
                rc = ci.main()
            except Exception as exc:  # noqa: BLE001 - ein Absturz ist ein Befund
                rc = f"Absturz {type(exc).__name__}: {exc}"
        return rc, prot.read_text().split(), puffer.getvalue()

    # Gemessen: b 50 s, a 30 s, c 10 s, d unbekannt; x gibt es nicht (mehr).
    dauern.write_text(json.dumps({"test_b.py": 50, "test_a.py": 30, "test_c.py": 10,
                                  "test_x.py": 5}))
    rc, start, ausgabe = sammellauf()
    erwartet = ["test_d.py", "test_b.py", "test_a.py", "test_c.py"]
    # Positivkontrolle: alle vier liefen, und die Erwartung ist NICHT alphabetisch
    if rc != 0 or sorted(start) != sorted(erwartet) or erwartet == sorted(erwartet):
        abbruch(f"Probelauf untauglich (rc={rc}, gestartet {start})\n{ausgabe[-800:]}")
    pruefe("Start: unbekannte zuerst, dann laengste zuerst", start == erwartet, start)
    ok_zeilen = [z.split()[1] for z in ausgabe.splitlines() if z.strip().startswith("OK")]
    pruefe("Ausgabe bleibt nach Namen sortiert", ok_zeilen == sorted(erwartet), ok_zeilen)
    try:
        neu = json.loads(dauern.read_text())
    except (OSError, ValueError) as exc:
        neu = {"_fehler": str(exc)}
    pruefe("Laufzeiten gespeichert: alle vier, neu gemessen (nicht die alten Werte)",
           all(isinstance(neu.get(f"test_{n}.py"), (int, float)) for n in "abcd")
           and neu.get("test_b.py", 50) < 50, neu)
    pruefe("Speichern MISCHT: ein nicht gelaufener Eintrag bleibt stehen",
           neu.get("test_x.py") == 5, neu)
    for inhalt, titel in (("kein json", "kaputte Datei"), ("[1, 2]", "falsche Form")):
        dauern.write_text(inhalt)
        rc, start, ausgabe = sammellauf()
        pruefe(f"{titel}: Lauf gruen und alphabetisch",
               rc == 0 and start == sorted(erwartet), (rc, start))
    dauern.unlink()
    rc, start, _ = sammellauf()
    pruefe("ohne Datei: alphabetisch, danach angelegt",
           rc == 0 and start == sorted(erwartet) and dauern.is_file(), (rc, start))
finally:
    ci.TESTS, ci.WURZEL, ci.AUSNAHMEN, sys.argv = alt
    if alt_env is None:
        os.environ.pop("JARVIS_CI_DAUERN", None)
    else:
        os.environ["JARVIS_CI_DAUERN"] = alt_env
    shutil.rmtree(tmp, ignore_errors=True)

# ═══ Teil D: Prolog-Waechter wertet die Beobachtung des Sammellaufs aus ═══
print("\nTeil D: ci_lauf.py + test_prolog_vollstaendig.js - Beobachtung aus dem Sammellauf")

import subprocess  # noqa: E402

NODE = shutil.which("node")
if not NODE:
    abbruch("node fehlt - Teil D misst nichts")
PROLOG = ci.PROLOG
tmp = Path(tempfile.mkdtemp(prefix="waechter-tempo-prolog-"))
vorher = set(Path.home().glob(".prolog_sammlung_*"))
alt = (ci.TESTS, ci.WURZEL, ci.AUSNAHMEN, sys.argv)
alt_env = os.environ.get("JARVIS_CI_DAUERN")
try:
    prot = tmp / "prot.jsonl"
    probe = tmp / "tests"
    probe.mkdir()
    # Zwei Pruefstaende mit Prolog (Auswahlregel: liest frontend/ UND ruft
    # .eval( - hier im Text), einer ohne, ein Python-Waechter, und ein
    # Prolog-Waechter, der festhaelt, was er vorfindet.
    meldung = ("const fs = require('fs');\n"
               "fs.appendFileSync(" + json.dumps(str(prot)) + ", JSON.stringify({wer: %s, "
               "pruefung: process.env.PROLOG_PRUEFUNG || null, sammlung: process.env.PROLOG_SAMMLUNG || null, "
               "inhalt: process.env.PROLOG_SAMMLUNG ? fs.readdirSync(process.env.PROLOG_SAMMLUNG).sort() : null, "
               "gelaufen: (() => { try { return JSON.parse(fs.readFileSync("
               "process.env.PROLOG_SAMMLUNG + '/_gelaufen.json', 'utf8')); } catch (e) { return null; } })()"
               "}) + '\\n');\n")
    for n in ("test_mit_a.js", "test_mit_b.js"):
        (probe / n).write_text("// readFileSync(path.join(ROOT, 'frontend/js/x.js')) ... w.eval(x)\n"
                               + meldung % json.dumps(n)
                               + "if (process.env.PROLOG_PRUEFUNG) fs.writeFileSync(process.env.PROLOG_PRUEFUNG, "
                                 "'{\"art\":\"fenster\"}\\n');\nconsole.log('Ergebnis: 1 OK, 0 FAIL');\n",
                               encoding="utf-8")
    (probe / "test_ohne.js").write_text(meldung % json.dumps("test_ohne.js")
                                        + "console.log('Ergebnis: 1 OK, 0 FAIL');\n", encoding="utf-8")
    (probe / "test_py.py").write_text(
        "import json, os\nwith open(%r, 'a') as f:\n    f.write(json.dumps({'wer': 'test_py.py', "
        "'pruefung': os.environ.get('PROLOG_PRUEFUNG')}) + '\\n')\nprint('Ergebnis: 1 OK, 0 FAIL')\n"
        % str(prot), encoding="utf-8")
    (probe / PROLOG).write_text(meldung % json.dumps(PROLOG) + "console.log('Ergebnis: 1 OK, 0 FAIL');\n",
                                encoding="utf-8")
    ci.TESTS, ci.WURZEL, ci.AUSNAHMEN = probe, tmp, tmp / "keine_ausnahmen.txt"
    os.environ["JARVIS_CI_DAUERN"] = str(tmp / "dauern.json")

    def sammellauf(*muster):
        if prot.exists():
            prot.unlink()
        sys.argv = ["ci_lauf.py", "--parallel", "4", *muster]
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer), contextlib.redirect_stderr(puffer):
            try:
                rc = ci.main()
            except Exception as exc:  # noqa: BLE001 - ein Absturz ist ein Befund
                rc = f"Absturz {type(exc).__name__}: {exc}"
        saetze = [json.loads(z) for z in prot.read_text().splitlines()] if prot.exists() else []
        return rc, {s["wer"]: s for s in saetze}, [s["wer"] for s in saetze], puffer.getvalue()

    rc, je, folge, ausgabe = sammellauf()
    if rc != 0 or len(je) != 5:
        abbruch(f"Probelauf untauglich (rc={rc}, gelaufen {sorted(je)})\n{ausgabe[-800:]}")
    pw = je[PROLOG]
    sammlung = pw.get("sammlung")
    pruefe("Prolog-Waechter laeuft NACH allen anderen", folge[-1] == PROLOG, folge)
    pruefe("…mit Sammlung, und die Liste nennt genau die beobachteten Laeufe",
           bool(sammlung) and pw.get("gelaufen") == ["test_mit_a.js", "test_mit_b.js"], pw)
    pruefe("…und ihre Beobachtungen liegen dort vor",
           {"test_mit_a.js.jsonl", "test_mit_b.js.jsonl"} <= set(pw.get("inhalt") or []), pw.get("inhalt"))
    pruefe("Beobachtung nur in Pruefstaenden mit Prolog (nicht ohne, nicht Python, nicht im Waechter)",
           all(je[n]["pruefung"] and str(je[n]["pruefung"]).startswith(str(sammlung or "?"))
               for n in ("test_mit_a.js", "test_mit_b.js"))
           and not je["test_ohne.js"]["pruefung"] and not je["test_py.py"]["pruefung"]
           and not pw["pruefung"], {n: s.get("pruefung") for n, s in je.items()})
    pruefe("Sammlung nach dem Lauf geloescht",
           bool(sammlung) and not Path(sammlung).exists()
           and set(Path.home().glob(".prolog_sammlung_*")) == vorher, sammlung)
    rc, je, folge, _ = sammellauf("test_mit_a.js")
    pruefe("ohne Prolog-Waechter im Lauf: keine Beobachtung (kein Mehraufwand)",
           rc == 0 and je.get("test_mit_a.js", {}).get("pruefung") is None, je)
finally:
    ci.TESTS, ci.WURZEL, ci.AUSNAHMEN, sys.argv = alt
    if alt_env is None:
        os.environ.pop("JARVIS_CI_DAUERN", None)
    else:
        os.environ["JARVIS_CI_DAUERN"] = alt_env
    shutil.rmtree(tmp, ignore_errors=True)
    # Eine Sammlung, die DIESER Probelauf liegen liess (gemeldet ist es oben),
    # gehoert nicht ins Home.
    for rest in set(Path.home().glob(".prolog_sammlung_*")) - vorher:
        shutil.rmtree(rest, ignore_errors=True)

# D2: der ECHTE Prolog-Waechter wertet eine Sammlung wirklich aus - eine
# Luecke darin muss er melden, ein Umgebungsname nicht. Alle Pruefstaende
# stehen als gelaufen in der Liste (nichts nachzustarten, Sekunden statt
# Minuten); nur einer hat eine Beobachtung.
auswahl = subprocess.run([NODE, str(TESTS / "lib" / "prolog_auswahl.js")], capture_output=True,
                         text=True, timeout=60)
try:
    alle = json.loads(auswahl.stdout)
except ValueError:
    alle = []
if not alle:
    abbruch("tests/lib/prolog_auswahl.js liefert keine Pruefstaende")
ziel_name = alle[0]
for name_fehlend, erwartet_rc, titel in (("_selSetze", 1, "eine Schnitt-Luecke in der Sammlung wird gemeldet"),
                                         ("fetch", 0, "ein Umgebungsname in der Sammlung bleibt gruen")):
    sml = Path(tempfile.mkdtemp(prefix="waechter-tempo-sammlung-"))
    try:
        (sml / "_gelaufen.json").write_text(json.dumps(alle))
        (sml / (ziel_name + ".jsonl")).write_text(
            json.dumps({"art": "fenster"}) + "\n"
            + json.dumps({"art": "eval", "zeichen": 10, "fehlend": [{"name": name_fehlend, "zeile": 1}]}) + "\n")
        r = subprocess.run([NODE, str(TESTS / "test_prolog_vollstaendig.js")], capture_output=True, text=True,
                           timeout=600, cwd=ROOT, env=dict(os.environ, PROLOG_SAMMLUNG=str(sml)))
        aus = r.stdout + r.stderr
    finally:
        shutil.rmtree(sml, ignore_errors=True)
    if "0 Pruefstaende selbst zu starten" not in aus:
        abbruch(f"Prolog-Waechter hat die Sammlung nicht uebernommen ({titel}):\n{aus[-600:]}")
    treffer = (ziel_name + " → " + name_fehlend) in aus
    pruefe(f"Prolog-Waechter: {titel}",
           r.returncode == erwartet_rc and treffer == (erwartet_rc == 1),
           f"rc={r.returncode}, gemeldet={treffer}")

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
