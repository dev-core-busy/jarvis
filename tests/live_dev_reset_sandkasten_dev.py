#!/usr/bin/env python3
"""Sandkasten-Probe fuer deploy/dev_reset.sh: Sicherung bei GELOESCHTEN Dateien.

VORFALL (2026-11-02, c+p ce4e6cc7): auf DEV waren zwei verfolgte Wachter per
scp-Deploy geloescht. `jarvis-dev-reset --uebernehmen` brach mit "Sicherung
fehlgeschlagen" ab - die Sicherungsliste kam aus der ANZEIGEFORM von
`git status --porcelain`, tar fand die geloeschten Pfade nicht. Fail-closed
richtig, aber jeder Reset nach einem ausgerollten Loeschen blieb haengen.
Dieselbe Anzeigeform brach an Umbenennungen ("R alt -> neu") und an Pfaden,
die git in Anfuehrungszeichen setzt (Umlaut, Leerzeichen am Rand ...).

Gemessen wird in einem WEGWERF-Repo (eigener bare-origin, Eigentuemer der
Dienstbenutzer) - nie gegen /opt/jarvis:
  1. --pruefen meldet die Abweichungen und aendert nichts (Exit 3)
  2. --uebernehmen sichert alles VORHANDENE (geaendert, umbenannt, Umlaut,
     Leerzeichen, unverfolgt), nennt die geloeschte Datei, setzt zurueck
     (Exit 0) - die geloeschte Datei ist danach wieder da
  3. die Sicherung enthaelt die geaenderten Inhalte (nicht die alten)

Aufruf AUF DEV als root (das Skript verlangt root und eine root-eigene Kopie):
    python3 /opt/jarvis/tests/live_dev_reset_sandkasten_dev.py [--skript <pfad>]
Vorgabe fuer --skript: deploy/dev_reset.sh neben diesem Test. Gegenprobe: mit
der Fassung VOR der Behebung muss Schritt 2 scheitern.
Zustand: Sandkasten, Skript-Kopie und die eigene Sicherung in /root werden am
Ende entfernt (nur die in DIESEM Lauf erzeugte, per Name aus der Ausgabe).
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
SKRIPT = HIER.parent / "deploy" / "dev_reset.sh"
if "--skript" in sys.argv:
    i = sys.argv.index("--skript")
    if i + 1 >= len(sys.argv):
        print("ABBRUCH: --skript ohne Pfad")
        sys.exit(2)
    SKRIPT = Path(sys.argv[i + 1])
NUTZER = "jarvis"

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


if os.geteuid() != 0:
    print("ABBRUCH: nur als root (das Skript verlangt es)")
    sys.exit(2)
try:
    pw = pwd.getpwnam(NUTZER)
except KeyError:
    print("ABBRUCH: Benutzer %s fehlt" % NUTZER)
    sys.exit(2)
if not SKRIPT.is_file():
    print("ABBRUCH: Skript fehlt: %s" % SKRIPT)
    sys.exit(2)

BASIS = Path(tempfile.mkdtemp(prefix="devreset-", dir="/tmp"))
KOPIE_DIR = Path(tempfile.mkdtemp(prefix="devreset-skript-", dir="/root"))
os.chmod(KOPIE_DIR, 0o755)
KOPIE = KOPIE_DIR / "dev_reset.sh"
shutil.copyfile(SKRIPT, KOPIE)
os.chmod(KOPIE, 0o755)
ARCHIVE = []


def als_nutzer(*args, cwd=None):
    return subprocess.run(["runuser", "-u", NUTZER, "--"] + list(args), cwd=cwd,
                          capture_output=True, text=True)


def git(*args, cwd):
    r = als_nutzer("git", *args, cwd=str(cwd))
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def lauf(*args):
    r = subprocess.run([str(KOPIE), "--dir", str(BAUM), "--dienst", "kein-dienst.service",
                        "--kein-neustart"] + list(args), capture_output=True, text=True)
    aus = r.stdout + r.stderr
    ARCHIVE.extend(re.findall(r"gesichert: (/root/dev-abweichungen-\S+\.tgz)", aus))
    return r.returncode, aus


BAUM = BASIS / "baum"
# Sicherungen in /root VOR dem Lauf: am Ende darf ausser den eigenen (die
# entfernt werden) nichts dazugekommen sein. Die Fassung vor 2026-11-02 liess
# bei gescheitertem tar ein ANGEFANGENES Archiv liegen, das --wiederherstellen
# als "neueste Sicherung" genommen haette.
VORHER_ARCHIVE = set(Path("/root").glob("dev-abweichungen-*.tgz"))
rc = 2
try:
    # ── Aufbau: bare-origin + Klon, alles dem Dienstbenutzer ──────────────
    os.chown(BASIS, pw.pw_uid, pw.pw_gid)
    als_nutzer("git", "init", "-q", "--bare", "-b", "master", str(BASIS / "origin.git"))
    als_nutzer("git", "clone", "-q", str(BASIS / "origin.git"), str(BAUM))
    if not (BAUM / ".git").is_dir():
        print("ABBRUCH: Sandkasten-Klon nicht angelegt")
        sys.exit(2)
    git("config", "user.email", "probe@beispiel.de", cwd=BAUM)
    git("config", "user.name", "Probe", cwd=BAUM)
    inhalte = {"weg.txt": "wird geloescht\n", "geaendert.txt": "alt\n",
               "umbenannt.txt": "umbenennen\n", "mit leer.txt": "alt\n"}
    for n, s in inhalte.items():
        (BAUM / n).write_text(s, encoding="utf-8")
        os.chown(BAUM / n, pw.pw_uid, pw.pw_gid)
    git("add", "-A", cwd=BAUM)
    git("commit", "-q", "-m", "Anfang", cwd=BAUM)
    git("push", "-q", "origin", "master", cwd=BAUM)
    ANFANG = git("rev-parse", "--short", "HEAD", cwd=BAUM).strip()

    # ── Abweichungen: genau die Formen, an denen die Anzeigeform bricht ───
    (BAUM / "weg.txt").unlink()
    (BAUM / "geaendert.txt").write_text("NEU\n", encoding="utf-8")
    (BAUM / "mit leer.txt").write_text("NEU\n", encoding="utf-8")
    git("mv", "umbenannt.txt", "umbenannt2.txt", cwd=BAUM)
    (BAUM / "unverfolgt ä.txt").write_text("frisch\n", encoding="utf-8")
    os.chown(BAUM / "unverfolgt ä.txt", pw.pw_uid, pw.pw_gid)
    st = git("status", "--porcelain", cwd=BAUM)
    if not (re.search(r"^ D weg\.txt$", st, re.M) and "->" in st and '"' in st):
        print("ABBRUCH: Aufbau stellt die Faelle nicht her (geloescht/umbenannt/gequotet):\n" + st)
        sys.exit(2)
    print("Aufbau: geloescht, geaendert, umbenannt, Leerzeichen, Umlaut (gequotet), unverfolgt")

    # ── 1. --pruefen ──────────────────────────────────────────────────────
    print("\n1. --pruefen")
    code, aus = lauf("--pruefen")
    check("Exit 3 (Abweichungen, nichts geaendert)", code == 3, "Exit %s\n%s" % (code, aus[-600:]))
    check("keine Sicherung angelegt", not ARCHIVE, str(ARCHIVE))
    check("weg.txt ist weiterhin geloescht", not (BAUM / "weg.txt").exists())

    # ── 2. --uebernehmen ──────────────────────────────────────────────────
    print("\n2. --uebernehmen")
    code, aus = lauf("--uebernehmen")
    check("Exit 0 (gesichert und zurueckgesetzt)", code == 0, "Exit %s\n%s" % (code, aus[-800:]))
    check("eine Sicherung wurde angelegt", len(ARCHIVE) == 1, str(ARCHIVE))
    check("die geloeschte Datei wird BENANNT", "geloescht" in aus and "weg.txt" in aus)
    check("weg.txt ist nach dem Reset wieder da", (BAUM / "weg.txt").is_file())
    check("geaendert.txt steht wieder auf dem alten Inhalt",
          (BAUM / "geaendert.txt").read_text(encoding="utf-8") == "alt\n")
    check("unverfolgte Datei ueberlebt den Reset", (BAUM / "unverfolgt ä.txt").is_file())
    check("HEAD unveraendert auf dem Anfang",
          git("rev-parse", "--short", "HEAD", cwd=BAUM).strip() == ANFANG)

    # ── 3. Inhalt der Sicherung ───────────────────────────────────────────
    print("\n3. Sicherung")
    if len(ARCHIVE) == 1 and Path(ARCHIVE[0]).is_file():
        with tarfile.open(ARCHIVE[0]) as t:
            namen = set(t.getnames())

            def inhalt(n):
                try:
                    return t.extractfile(n).read().decode("utf-8")
                except Exception:  # noqa: BLE001
                    return None
            for n in ("geaendert.txt", "mit leer.txt"):
                check("%s mit NEUEM Inhalt gesichert" % n, inhalt(n) == "NEU\n", str(inhalt(n)))
            check("umbenannt2.txt (Ziel der Umbenennung) gesichert", "umbenannt2.txt" in namen)
            check("unverfolgt ä.txt (gequoteter Name) gesichert", "unverfolgt ä.txt" in namen)
            check("weg.txt NICHT im Archiv (nichts zu sichern)", "weg.txt" not in namen)
            check("kein Anzeige-Rest als Name (\"…\" oder ->)",
                  not [n for n in namen if '"' in n or "->" in n], str(sorted(namen)))
    else:
        check("Sicherung lesbar", False, str(ARCHIVE))

    print("\n4. Rueckstaende")
    neu = set(Path("/root").glob("dev-abweichungen-*.tgz")) - VORHER_ARCHIVE - {Path(a) for a in ARCHIVE}
    check("kein angefangenes oder fremdes Archiv in /root hinterlassen", not neu, str(sorted(neu)))
    for n in neu:
        n.unlink()   # Rueckstand dieses Laufs - nicht stehen lassen

    rc = 0 if _fail == 0 else 1
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 2
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: %r" % e)
    rc = 2
finally:
    shutil.rmtree(BASIS, ignore_errors=True)
    shutil.rmtree(KOPIE_DIR, ignore_errors=True)
    for a in ARCHIVE:
        try:
            os.unlink(a)
        except OSError:
            pass
print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(rc)
