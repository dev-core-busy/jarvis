#!/usr/bin/env python3
"""Waechter: die ROOT-Seite von lauf_tmp folgt keinem Symlink (Code-Review 2026-10-07).

Befund: ``arbeit_bereitstellen`` und ``einhaengepunkte`` laufen im Broker als root
(Op ``sandbox_lauf``, automatisch erlaubt) und riefen ``mkdir(exist_ok)``,
``os.chown`` und ``os.chmod`` ueber PFADE auf. ``/tmp/jarvis-arbeit`` gehoert dem
Dienstbenutzer und ist nicht sticky – ``fs.protected_symlinks`` greift dort
nicht. Ein Symlink ``/tmp/jarvis-arbeit/<kennung> -> /etc`` gab ``/etc`` damit
die Dienstgruppe und Modus 2770: ein Weg vom Dienstbenutzer zu root.

Gemessen an der WIRKUNG mit dem echten Modul ``backend.lauf_tmp`` in einem
Wegwerf-Verzeichnis. Root wird nachgestellt: ``os.geteuid`` liefert 0,
``os.fchown``/``os.chown`` ZEICHNEN AUF, auf welches Verzeichnis sie zielen (ein
Nicht-root darf nicht fremd-chownen). ``fchmod``/``chmod`` laufen echt – die
Verzeichnisse gehoeren dem Pruefer, eine Modusaenderung am Opfer waere also
sichtbar.

  * Positivkontrolle: frische Kennung -> Verzeichnis, Eigentuemerwechsel am
    RICHTIGEN Ort, Modus 2770. Ohne sie waeren die Abweisungen trivial.
  * Kennung als Symlink nach aussen -> None, Opfer unberuehrt (Modus, kein chown).
  * ARBEIT_ROOT selbst als Symlink -> Opfer unberuehrt.
  * Einhaengepunkt mit Symlink-Teil -> Opfer unberuehrt; echter Teil wird versorgt.
  * ``_verzeichnis_fd`` weist ``..`` und Symlinks ab.

    python3 tests/test_lauf_tmp_symlink.py
"""
import getpass
import importlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % label)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (label, (" – %s" % detail) if detail else ""))


def abbruch(grund):
    """"Konnte nicht laufen" ist nicht "bestanden" – Exit 2."""
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


if os.geteuid() == 0:
    abbruch("als root ausgefuehrt – die Attrappen wuerden echte Eigentuemer aendern")
if not Path("/proc/self/fd").is_dir():
    abbruch("/proc/self/fd fehlt – Ziel eines Deskriptors nicht bestimmbar")

try:
    LT = importlib.import_module("backend.lauf_tmp")
except Exception as e:  # noqa: BLE001
    abbruch("backend.lauf_tmp nicht importierbar: %s" % e)

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jv_lauf_link_")).resolve()
OPFER = SANDKASTEN / "etc"
ICH = getpass.getuser()

# ── Root nachstellen ───────────────────────────────────────────────────────
_echt = {"geteuid": os.geteuid, "fchown": os.fchown, "chown": os.chown}
chowns = []   # (aufgeloester Zielpfad, uid, gid)


def _fd_ziel(fd):
    return os.path.realpath(os.readlink("/proc/self/fd/%d" % fd))


def _fchown(fd, uid, gid):
    chowns.append((_fd_ziel(fd), uid, gid))


def _chown(pfad, uid, gid, *a, **k):
    # Pfadbasiert: folgt (wie das echte os.chown) dem Symlink.
    chowns.append((os.path.realpath(pfad), uid, gid))


os.geteuid = lambda: 0
os.fchown = _fchown
os.chown = _chown


def aufbauen():
    chowns.clear()
    for p in (SANDKASTEN / "tmp", OPFER):
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.exists():
            shutil.rmtree(p)
    (SANDKASTEN / "tmp").mkdir()
    OPFER.mkdir(mode=0o755)
    os.chmod(OPFER, 0o755)
    (OPFER / "passwd").write_text("root:x:0:0\n", encoding="utf-8")
    LT.ARBEIT_ROOT = SANDKASTEN / "tmp" / "jarvis-arbeit"


def opfer_heil(label):
    modus = stat.S_IMODE(OPFER.stat().st_mode)
    check(modus == 0o755, "%s: Modus des Opfers unveraendert (0755)" % label, oct(modus))
    getroffen = [c for c in chowns if c[0] == str(OPFER) or c[0].startswith(str(OPFER) + "/")]
    check(not getroffen, "%s: kein chown auf das Opfer" % label, str(getroffen))


try:
    print("\n\033[1mPositivkontrolle\033[0m")
    aufbauen()
    erg = LT.arbeit_bereitstellen("deadbeef", ICH)
    ziel = LT.ARBEIT_ROOT / "deadbeef"
    check(erg == ziel, "frische Kennung -> Verzeichnis", repr(erg))
    check(ziel.is_dir() and not ziel.is_symlink(), "Verzeichnis existiert als echtes Verzeichnis")
    check(any(c[0] == str(ziel) for c in chowns), "Eigentuemerwechsel am richtigen Ort",
          str(chowns))
    modus = stat.S_IMODE(ziel.stat().st_mode) if ziel.exists() else None
    check(modus == LT.ARBEIT_MODUS, "Modus 2770 gesetzt", oct(modus or 0))
    if _fail:
        abbruch("Positivkontrolle gescheitert – die Abweisungen waeren trivial")

    print("\n\033[1mKennung ist ein Symlink nach aussen\033[0m")
    aufbauen()
    LT._wurzel_sicherstellen(LT.ARBEIT_ROOT, 0o755)
    os.symlink(OPFER, LT.ARBEIT_ROOT / "cafebabe")
    erg = LT.arbeit_bereitstellen("cafebabe", ICH)
    check(erg is None, "arbeit_bereitstellen -> None", repr(erg))
    opfer_heil("Kennung-Symlink")

    print("\n\033[1mARBEIT_ROOT selbst ist ein Symlink\033[0m")
    aufbauen()
    os.symlink(OPFER, LT.ARBEIT_ROOT)
    LT._wurzel_sicherstellen(LT.ARBEIT_ROOT, 0o755)
    erg = LT.arbeit_bereitstellen("deadbeef", ICH)
    check(erg is None, "arbeit_bereitstellen -> None", repr(erg))
    check(not (OPFER / "deadbeef").exists(), "nichts im Opfer angelegt")
    opfer_heil("Wurzel-Symlink")

    print("\n\033[1mEinhaengepunkt mit Symlink-Teil\033[0m")
    aufbauen()
    lauf = LT.arbeit_bereitstellen("abcdef12", ICH)
    if lauf is None:
        abbruch("Lauf-Verzeichnis fuer den Einhaengepunkt-Fall nicht angelegt")
    os.symlink(OPFER, Path(lauf) / "boese")
    chowns.clear()
    LT.einhaengepunkte(lauf, ["/tmp/boese/unter", "/tmp/gut/unter"], ICH)
    opfer_heil("Einhaengepunkt-Symlink")
    check(not (OPFER / "unter").exists(), "nichts im Opfer angelegt")
    gut = Path(lauf) / "gut" / "unter"
    check(gut.is_dir(), "echter Einhaengepunkt daneben wird angelegt")
    check(any(c[0] == str(gut) for c in chowns), "…und bekommt seinen Eigentuemer", str(chowns))

    print("\n\033[1m_verzeichnis_fd\033[0m")
    aufbauen()
    os.symlink(OPFER, SANDKASTEN / "tmp" / "link")
    for pfad, name in ((SANDKASTEN / "tmp" / "link", "Symlink als letzter Teil"),
                       (SANDKASTEN / "tmp" / "link" / "x", "Symlink als Zwischenteil"),
                       (Path(str(SANDKASTEN / "tmp") + "/../etc"), "'..' im Pfad")):
        try:
            fd = LT._verzeichnis_fd(pfad, 0o700)
            os.close(fd)
            check(False, "%s wird abgewiesen" % name)
        except (OSError, ValueError):
            check(True, "%s wird abgewiesen" % name)
    check(not (OPFER / "x").exists(), "kein Verzeichnis im Opfer angelegt")
finally:
    os.geteuid, os.fchown, os.chown = _echt["geteuid"], _echt["fchown"], _echt["chown"]
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
