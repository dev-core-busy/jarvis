#!/usr/bin/env python3
"""Waechter: der Wegwerf-Klon des Claude-Subagenten ist nicht fuer jeden offen.

Befund 2026-11-27: die Arbeitskopien unter /tmp/claude_subagent/<job> standen
auf 0777 – jeder lokale Prozess konnte sie veraendern, bevor daraus der Patch
entstand, den der Benutzer anwendet. Jetzt: Wurzel 0755 und dienst-eigen,
Auftragsordner 0770 + ACL fuer die Sandbox-Konten (``_tor_setzen``).

Gemessen an der WIRKUNG mit echtem git und echtem setfacl, Wurzel in einem
Wegwerf-Verzeichnis, Klon aus einem lokalen Probe-Repo:
  * Positivkontrolle: Klon entsteht, Basis passt
  * Auftragsordner: Modus 0770 (keine Rechte fuer "andere"), ACL nennt die Konten
  * innen: Ausfuehrbit erhalten, Symlink-ZIEL ausserhalb unveraendert
  * Wurzel ist ein Symlink → Abbruch; Wurzel 0777 → auf 0755 korrigiert
  * setfacl scheitert (unbekanntes Konto) → Abbruch, Ordner entfernt (fail-closed)
  * nur als root mit echten Sandbox-Konten (DEV): ``nobody`` kommt NICHT hinein,
    ``jarvis_sandbox_noinet`` kann im Klon schreiben

    python3 tests/test_claude_subagent_tor.py   Exit 0 gruen, 1 rot, 2 konnte nicht laufen
"""
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


for werkzeug in ("git", "setfacl", "getfacl"):
    if not shutil.which(werkzeug):
        print(f"ABBRUCH: {werkzeug} fehlt")
        sys.exit(2)

from backend import claude_subagent as cs  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="csa_tor_"))
os.chmod(TMP, 0o755)
cs.STATE_PATH = TMP / "zustand.json"
cs.ARBEIT_ROOT = TMP / "arbeit"
if str(ROOT) in str(cs.ARBEIT_ROOT):
    print("ABBRUCH: ARBEIT_ROOT zeigt ins Repo")
    sys.exit(2)

# Probe-Repo: Skript mit x-Bit, normale Datei, Symlink auf eine Datei AUSSERHALB
REPO = TMP / "repo"
REPO.mkdir()
AUSSEN = TMP / "aussen.txt"
AUSSEN.write_text("fremd")
os.chmod(AUSSEN, 0o600)


def _git(*a, cwd=REPO):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@beispiel.de",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@beispiel.de"})
    if r.returncode != 0:
        print(f"ABBRUCH: git {a[0]}: {r.stderr.strip()[:200]}")
        sys.exit(2)
    return r.stdout.strip()


_git("init", "-q", "-b", "master")
(REPO / "lauf.sh").write_text("#!/bin/sh\necho hi\n")
os.chmod(REPO / "lauf.sh", 0o755)
(REPO / "text.txt").write_text("a\n")
os.symlink(str(AUSSEN), REPO / "verweis")
_git("add", "-A")
_git("commit", "-q", "-m", "probe")
KOPF = _git("rev-parse", "HEAD")
cs._repo_url = lambda: "file://" + str(REPO)

ICH = pwd.getpwuid(os.getuid()).pw_name
ALS_ROOT = os.geteuid() == 0
ECHTE_KONTEN = all(_k in {p.pw_name for p in pwd.getpwall()}
                   for _k in ("jarvis_sandbox", "jarvis_sandbox_noinet"))
if not (ALS_ROOT and ECHTE_KONTEN):
    # Lokal gibt es die Sandbox-Konten nicht – setfacl braucht ein bestehendes Konto
    cs._sandbox_konten = lambda: (ICH,)


def _modus(p):
    return os.lstat(p).st_mode & 0o7777


print("Klon und Tor")
work, fehler = cs.arbeitsbereich_anlegen("job1", KOPF[:12])
if fehler or not (work / "lauf.sh").is_file():
    print(f"ABBRUCH: Positivkontrolle – Klon entsteht nicht ({fehler})")
    sys.exit(2)
check(True, "Positivkontrolle: Klon entsteht, Basis passt")
ziel = cs.ARBEIT_ROOT / "job1"
check(_modus(ziel) == 0o770, f"Auftragsordner 0770 (ist {oct(_modus(ziel))})")
check(_modus(ziel) & 0o007 == 0, "Auftragsordner: keine Rechte fuer 'andere'")
acl = subprocess.run(["getfacl", "-p", str(ziel)], capture_output=True, text=True).stdout
konten = cs._sandbox_konten()
check(all(f"user:{k}:rwx" in acl for k in konten), f"ACL nennt {konten}")
check(_modus(cs.ARBEIT_ROOT) == 0o755, f"Wurzel 0755 (ist {oct(_modus(cs.ARBEIT_ROOT))})")
check(_modus(work / "lauf.sh") == 0o777, "innen: Ausfuehrbit erhalten (0777)")
check(_modus(work / "text.txt") == 0o666, "innen: Datei 0666")
check(_modus(AUSSEN) == 0o600, f"Symlink-ZIEL ausserhalb unveraendert (ist {oct(_modus(AUSSEN))})")

print("Wurzel")
cs.aufraeumen("job1")
os.chmod(cs.ARBEIT_ROOT, 0o777)
work, fehler = cs.arbeitsbereich_anlegen("job2", KOPF[:12])
check(not fehler and _modus(cs.ARBEIT_ROOT) == 0o755, "Wurzel 0777 → auf 0755 korrigiert")
cs.aufraeumen("job2")
shutil.rmtree(cs.ARBEIT_ROOT)
FREMD = TMP / "fremd"
FREMD.mkdir()
os.symlink(FREMD, cs.ARBEIT_ROOT)
work, fehler = cs.arbeitsbereich_anlegen("job3", KOPF[:12])
check(bool(fehler) and not any(FREMD.iterdir()), f"Wurzel als Symlink → Abbruch, nichts angelegt ({fehler})")
os.unlink(cs.ARBEIT_ROOT)

print("fail-closed")
_alt = cs._sandbox_konten
cs._sandbox_konten = lambda: ("konto_gibt_es_nicht_xyz",)
work, fehler = cs.arbeitsbereich_anlegen("job4", KOPF[:12])
check(bool(fehler) and "setfacl" in fehler, f"setfacl scheitert → Fehler ({(fehler or '')[:60]})")
check(not (cs.ARBEIT_ROOT / "job4").exists(), "…und der Auftragsordner ist entfernt")
cs._sandbox_konten = _alt

if ALS_ROOT and ECHTE_KONTEN:
    print("Echte Konten (root)")
    # Als root gehoert der Klon root – im Dienst gehoert er dem Dienstbenutzer.
    # Gemessen wird das Tor, nicht der Eigentuemer.
    work, fehler = cs.arbeitsbereich_anlegen("job5", KOPF[:12])
    check(not fehler, f"Klon mit echten Konten ({fehler})")
    z = cs.ARBEIT_ROOT / "job5"
    r = subprocess.run(["runuser", "-u", "nobody", "--", "ls", str(z)], capture_output=True)
    check(r.returncode != 0, "nobody kommt NICHT in den Auftragsordner")
    r = subprocess.run(["runuser", "-u", "nobody", "--", "sh", "-c",
                        f"echo x >> {work}/text.txt"], capture_output=True)
    check(r.returncode != 0, "nobody kann keine Datei im Klon veraendern")
    r = subprocess.run(["runuser", "-u", "jarvis_sandbox_noinet", "--", "sh", "-c",
                        f"echo x >> {work}/text.txt && touch {work}/neu.txt"], capture_output=True)
    check(r.returncode == 0, "jarvis_sandbox_noinet kann im Klon schreiben")
    cs.aufraeumen("job5")
    # Wurzel, die ein Fremder vorab angelegt hat (in /tmp kann das jeder)
    nobody = pwd.getpwnam("nobody")
    os.chown(cs.ARBEIT_ROOT, nobody.pw_uid, nobody.pw_gid)
    work, fehler = cs.arbeitsbereich_anlegen("job6", KOPF[:12])
    check(bool(fehler) and "gehoert nicht dem Dienst" in fehler
          and not (cs.ARBEIT_ROOT / "job6").exists(),
          f"fremde Wurzel → Abbruch, nichts angelegt ({(fehler or '')[:50]})")
    os.chown(cs.ARBEIT_ROOT, 0, 0)
else:
    print("  (Abschnitt 'echte Konten' nur als root mit Sandbox-Konten – hier uebersprungen)")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
