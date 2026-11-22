#!/usr/bin/env python3
"""Waechter: ``ci_lauf.py --nur-betroffene`` laesst nur aus, was sich wirklich nicht geaendert hat.

WARUM (2026-11-22): ein Waechter, der faelschlich uebersprungen wird, ist ein
Loch - und es faellt nicht auf, denn der Lauf ist gruen. Deshalb wird hier
jede Zusage einzeln gemessen (Regel: tests/lib/betroffen.py, Lesespur:
tests/lib/lesespur.py):

  Teil A  der strace-Parser an synthetischen Zeilen: Arbeitsverzeichnis je
          Prozess (chdir, Kinder erben es), unterbrochene Zeilen, Deskriptor-
          Pfade (-y), Verzeichnisse (O_DIRECTORY), fehlende Pfade zaehlen,
          reines Schreiben nicht; .git, Bytecode und Fluechtiges fallen weg.
  Teil B  die ECHTE Aufzeichnung ueber einen Prozessbaum: Python liest
          selbst, startet bash (cat) und node (readFileSync), listet ein
          Verzeichnis und fragt einen fehlenden Pfad ab - alles muss in der
          Spur stehen. Eine Python- oder Node-Instrumentierung saehe die
          Kinder nicht; genau dafuer ist strace da.
  Teil C  die Regeln der Karte: unveraendert -> entfaellt; Inhalt, neue
          Datei im gelisteten Verzeichnis, entstandener Pfad, rot, zu alt,
          andere Umgebung, kaputte Karte -> laeuft.
  Teil D  ci_lauf.py an einem Wegwerf-Testordner, Lauf fuer Lauf.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen (strace/node fehlt).
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
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


STRACE, NODE = shutil.which("strace"), shutil.which("node")
if not STRACE or not NODE:
    abbruch("strace oder node fehlt - die Lesespur ist nicht messbar")

import betroffen  # noqa: E402
import lesespur  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="waechter-betroffen-"))
alt_env = {k: os.environ.get(k) for k in ("JARVIS_WAECHTER_KARTE", "JARVIS_CI_DAUERN",
                                          "JARVIS_BETROFFEN_MAX_ALTER_H")}
try:
    # ═══ Teil A: Parser ═════════════════════════════════════════════════
    print("Teil A: strace-Parser (tests/lib/lesespur.py)")
    W = "/w"
    SPUR = "\n".join([
        '100 openat(AT_FDCWD, "/w/abs.txt", O_RDONLY|O_CLOEXEC) = 3',
        '100 openat(AT_FDCWD, "rel.txt", O_RDONLY) = 3',
        '100 chdir("sub") = 0',
        '100 openat(AT_FDCWD, "nach_chdir.txt", O_RDONLY) = 3',
        '100 clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|SIGCHLD) = 200',
        '200 openat(AT_FDCWD, "im_kind.txt", O_RDONLY) = 3',
        '100 openat(AT_FDCWD, "/w/liste", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = 4',
        '100 openat(AT_FDCWD, "/w/geschrieben.txt", O_WRONLY|O_CREAT|O_TRUNC, 0644) = 5',
        '100 openat(AT_FDCWD, "/w/beides.txt", O_RDWR|O_CREAT, 0644) = 5',
        '100 newfstatat(AT_FDCWD, "/w/fehlt.txt", 0x7ffc, 0) = -1 ENOENT (No such file or directory)',
        '300 openat(AT_FDCWD, "/w/unterbrochen.txt", O_RDONLY <unfinished ...>',
        '100 execve("/w/skript.sh", ["/w/skript.sh"], 0x7ffd /* 30 vars */) = 0',
        '300 <... openat resumed>) = 6',
        '100 openat(7</w/dirfd>, "darin.txt", O_RDONLY) = 8',
        '100 unlinkat(AT_FDCWD, "/w/weg.txt", 0) = 0',
        '100 openat(AT_FDCWD, "/w/mit, komma.txt", O_RDONLY) = 9',
        '100 +++ exited with 0 +++',
    ])
    gelesen, verz = lesespur.auswerten(SPUR, W)
    erwartet = {"/w/abs.txt", "/w/rel.txt", "/w/sub/nach_chdir.txt", "/w/sub/im_kind.txt",
                "/w/beides.txt", "/w/fehlt.txt", "/w/unterbrochen.txt", "/w/skript.sh",
                "/w/dirfd/darin.txt", "/w/mit, komma.txt"}
    for p in sorted(erwartet):
        pruefe(f"gelesen: {p}", p in gelesen, sorted(gelesen))
    pruefe("Verzeichnis zum Auflisten (O_DIRECTORY) erkannt", verz == {"/w/liste"}, verz)
    pruefe("nur geschrieben / geloescht ist KEINE Abhaengigkeit",
           "/w/geschrieben.txt" not in gelesen and "/w/weg.txt" not in gelesen)
    repo, draussen = lesespur.einteilen(
        {"/w/a.py", "/w/.git/HEAD", "/w/x/__pycache__/a.cpython-313.pyc", "/proc/self/status",
         "/tmp/z", str(Path.home() / ".cache/jarvis/k.json"), "/usr/lib/python3/os.py"}, W)
    pruefe("einteilen: Repo relativ, .git/Bytecode/Fluechtiges weg, Bibliothek bleibt",
           repo == {"a.py"} and draussen == {"/usr/lib/python3/os.py"}, (repo, draussen))
    # Ein Verweis auf Fluechtiges ist fluechtig (/etc/mtab -> /proc/self/mounts:
    # Aenderungszeit immer "jetzt", der Waechter liefe sonst bei jedem Lauf).
    verweis = Path.home() / ("jarvis-lesespur-probe-%d" % os.getpid())
    try:
        verweis.symlink_to("/proc/self/mounts")
        _, draussen = lesespur.einteilen({str(verweis)}, W)
        pruefe("Verweis auf /proc faellt heraus (wie /etc/mtab)", not draussen, draussen)
    finally:
        verweis.unlink(missing_ok=True)

    # ═══ Teil B: echte Aufzeichnung ══════════════════════════════════════
    print("\nTeil B: echte Aufzeichnung ueber einen Prozessbaum (Python, bash, node)")
    w = tmp / "baum"
    (w / "liste").mkdir(parents=True)
    for n in ("selbst.txt", "per_bash.txt", "per_node.txt"):
        (w / n).write_text(n)
    probe = w / "probe.py"
    probe.write_text(
        "import os, subprocess\n"
        "open('selbst.txt').read()\n"
        "subprocess.run(['bash', '-c', 'cat per_bash.txt > /dev/null'])\n"
        f"subprocess.run([{NODE!r}, '-e', \"require('fs').readFileSync('per_node.txt')\"])\n"
        "os.listdir('liste')\n"
        "os.path.exists('noch_nicht_da.txt')\n")
    spur = tmp / "probe.st"
    r = subprocess.run([STRACE, *lesespur.STRACE_ARGUMENTE, "-o", str(spur), sys.executable, str(probe)],
                       cwd=w, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not spur.is_file():
        abbruch(f"strace-Probe lief nicht (rc={r.returncode}): {r.stderr.strip()[-300:]}")
    g, v = lesespur.auswerten(spur.read_text(errors="replace"), w)
    rg, _ = lesespur.einteilen(g, w)
    rv, _ = lesespur.einteilen(v, w)
    for n, wie in (("selbst.txt", "Python selbst"), ("per_bash.txt", "Kindprozess bash"),
                   ("per_node.txt", "Kindprozess node"), ("noch_nicht_da.txt", "fehlender Pfad"),
                   ("probe.py", "das Skript selbst")):
        pruefe(f"Spur enthaelt {n} ({wie})", n in rg, sorted(rg)[:12])
    pruefe("Spur enthaelt das aufgelistete Verzeichnis", "liste" in rv, sorted(rv))

    # ═══ Teil C: Regeln der Karte ════════════════════════════════════════
    print("\nTeil C: Regeln der Karte (tests/lib/betroffen.py)")
    w = tmp / "regeln"
    (w / "verz").mkdir(parents=True)
    (w / "a.txt").write_text("1")
    karte_datei = tmp / "karte_c.json"

    def neue_karte(kennung="k1"):
        return betroffen.Karte(kennung, datei=karte_datei)

    z = lesespur.Zustaende(w)
    k = neue_karte()
    pruefe("ohne Karte: laeuft", k.grund("x", z) is not None)
    jetzt = time.time()
    k.eintragen("x", 0, jetzt, {"a.txt", "fehlt.txt"}, {"verz"}, z)
    k.eintragen("rot", 1, jetzt, {"a.txt"}, set(), z)
    k.speichern()
    k = neue_karte()
    pruefe("unveraendert seit gruenem Lauf: entfaellt", k.grund("x", lesespur.Zustaende(w)) is None)
    pruefe("zuletzt rot: laeuft trotz gleicher Abhaengigkeiten",
           k.grund("rot", lesespur.Zustaende(w)) == "zuletzt nicht gruen")
    (w / "a.txt").write_text("2")
    pruefe("Inhalt einer Abhaengigkeit geaendert: laeuft",
           k.grund("x", lesespur.Zustaende(w)) == "Abhaengigkeit geaendert")
    (w / "a.txt").write_text("1")
    (w / "verz" / "neu.txt").write_text("")
    pruefe("neue Datei im aufgelisteten Verzeichnis: laeuft",
           k.grund("x", lesespur.Zustaende(w)) == "Abhaengigkeit geaendert")
    (w / "verz" / "neu.txt").unlink()
    (w / "verz" / ".prolog_sammlung_abc").mkdir()
    pruefe("fluechtige Ablage im aufgelisteten Verzeichnis aendert nichts (das Home!)",
           k.grund("x", lesespur.Zustaende(w)) is None)
    (w / "verz" / ".prolog_sammlung_abc").rmdir()
    (w / "fehlt.txt").write_text("")
    pruefe("ein zuvor fehlender Pfad ist entstanden: laeuft",
           k.grund("x", lesespur.Zustaende(w)) == "Abhaengigkeit geaendert")
    (w / "fehlt.txt").unlink()
    pruefe("…und zurueck im alten Zustand: entfaellt wieder", k.grund("x", lesespur.Zustaende(w)) is None)
    os.environ["JARVIS_BETROFFEN_MAX_ALTER_H"] = "1"
    pruefe("aelter als die Altersgrenze: laeuft",
           k.grund("x", lesespur.Zustaende(w), jetzt=jetzt + 7200) is not None)
    os.environ.pop("JARVIS_BETROFFEN_MAX_ALTER_H")
    pruefe("andere Umgebung (Kennung): kein Eintrag gilt",
           neue_karte("k2").grund("x", lesespur.Zustaende(w)) == "kein Eintrag")
    karte_datei.write_text("{kaputt")
    pruefe("kaputte Karte: laeuft, kein Absturz", neue_karte().grund("x", lesespur.Zustaende(w)) == "kein Eintrag")

    # ═══ Teil D: ci_lauf.py am Wegwerf-Testordner ═══════════════════════
    print("\nTeil D: ci_lauf.py --nur-betroffene, Lauf fuer Lauf")
    spec = importlib.util.spec_from_file_location("ci_lauf_betroffen", TESTS / "ci_lauf.py")
    ci = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci)
    w = tmp / "ci"
    probe_t = w / "tests"
    (w / "daten" / "verz").mkdir(parents=True)
    probe_t.mkdir()
    (w / "daten" / "a.txt").write_text("a")
    (w / "daten" / "b.txt").write_text("b")
    prot = tmp / "start.txt"
    melden = f"open({str(prot)!r}, 'a').write(__file__.rsplit('/', 1)[-1] + '\\n')\n"
    (probe_t / "test_a.py").write_text(melden + "open('daten/a.txt').read()\nprint('Ergebnis: 1 OK, 0 FAIL')\n")
    (probe_t / "test_b.js").write_text(
        f"require('fs').appendFileSync({json.dumps(str(prot))}, 'test_b.js\\n');\n"
        "require('fs').readFileSync('daten/b.txt');\nconsole.log('Ergebnis: 1 OK, 0 FAIL');\n")
    (probe_t / "test_c.py").write_text(melden + "import os\nos.listdir('daten/verz')\nprint('Ergebnis: 1 OK, 0 FAIL')\n")
    (probe_t / "test_rot.py").write_text(melden + "import sys\nprint('  FAIL absichtlich')\nsys.exit(1)\n")
    alt = (ci.TESTS, ci.WURZEL, ci.AUSNAHMEN, sys.argv)
    ci.TESTS, ci.WURZEL, ci.AUSNAHMEN = probe_t, w, w / "keine_ausnahmen.txt"
    os.environ["JARVIS_WAECHTER_KARTE"] = str(tmp / "karte_d.json")
    os.environ["JARVIS_CI_DAUERN"] = str(tmp / "dauern_d.json")

    def sammellauf(*zusatz):
        prot.write_text("")
        sys.argv = ["ci_lauf.py", "--parallel", "2", *zusatz]
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer), contextlib.redirect_stderr(puffer):
            try:
                rc = ci.main()
            except Exception as exc:  # noqa: BLE001 - ein Absturz ist ein Befund
                rc = f"Absturz {type(exc).__name__}: {exc}"
        return rc, sorted(prot.read_text().split()), puffer.getvalue()

    try:
        ALLE = ["test_a.py", "test_b.js", "test_c.py", "test_rot.py"]
        rc, gestartet, aus = sammellauf("--nur-betroffene")
        if gestartet != ALLE:
            abbruch(f"erster Lauf startete nicht alle ({gestartet}, rc={rc})\n{aus[-600:]}")
        pruefe("erster Lauf: alle laufen und werden aufgezeichnet (rc 1 wegen test_rot)", rc == 1, rc)
        rc, gestartet, aus = sammellauf("--nur-betroffene")
        pruefe("nichts geaendert: nur der rote laeuft wieder", gestartet == ["test_rot.py"], gestartet)
        pruefe("…und die Bilanz nennt die nicht gestarteten", "nicht gestartet: 3" in aus, aus[-300:])
        (w / "daten" / "a.txt").write_text("a2")
        rc, gestartet, _ = sammellauf("--nur-betroffene")
        pruefe("gelesene Datei geaendert (Python): genau ihr Waechter laeuft",
               gestartet == ["test_a.py", "test_rot.py"], gestartet)
        (w / "daten" / "b.txt").write_text("b2")
        rc, gestartet, _ = sammellauf("--nur-betroffene")
        pruefe("gelesene Datei geaendert (Node): genau ihr Waechter laeuft",
               gestartet == ["test_b.js", "test_rot.py"], gestartet)
        (w / "daten" / "verz" / "neu.txt").write_text("")
        rc, gestartet, _ = sammellauf("--nur-betroffene")
        pruefe("neue Datei im aufgelisteten Verzeichnis: der Auflister laeuft",
               gestartet == ["test_c.py", "test_rot.py"], gestartet)
        (probe_t / "test_a.py").write_text((probe_t / "test_a.py").read_text() + "# geaendert\n")
        rc, gestartet, _ = sammellauf("--nur-betroffene")
        pruefe("der Waechter selbst geaendert: er laeuft", gestartet == ["test_a.py", "test_rot.py"], gestartet)
        rc, gestartet, _ = sammellauf()
        pruefe("ohne --nur-betroffene: alle laufen wie gewohnt", gestartet == ALLE, gestartet)
        os.environ["JARVIS_BETROFFEN_MAX_ALTER_H"] = "0"
        rc, gestartet, _ = sammellauf("--nur-betroffene")
        pruefe("Altersgrenze 0: alle laufen", gestartet == ALLE, gestartet)
        os.environ.pop("JARVIS_BETROFFEN_MAX_ALTER_H")
        # Unter Aufzeichnung gilt ein Vielfaches des Zeitdeckels: test_langsam
        # braucht 1,5 s bei 1 s Deckel - ohne Aufzeichnung waere das ein Zeitdeckel.
        (probe_t / "test_langsam.py").write_text(melden + "import time\ntime.sleep(1.5)\n"
                                                 "print('Ergebnis: 1 OK, 0 FAIL')\n")
        rc, gestartet, aus = sammellauf("--nur-betroffene", "--zeitdeckel", "1", "test_langsam.py")
        pruefe("unter Aufzeichnung gilt ein Vielfaches des Zeitdeckels",
               rc == 0 and gestartet == ["test_langsam.py"], (rc, aus[-200:]))
        (probe_t / "test_langsam.py").unlink()
        rc, gestartet, _ = sammellauf("--nur-betroffene", "test_a.py")
        rc2, gestartet2, _ = sammellauf("--nur-betroffene")
        pruefe("ein Teillauf (Muster) loescht die Eintraege der anderen nicht",
               gestartet2 == ["test_rot.py"], gestartet2)
    finally:
        ci.TESTS, ci.WURZEL, ci.AUSNAHMEN, sys.argv = alt
finally:
    for k, v in alt_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(tmp, ignore_errors=True)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
