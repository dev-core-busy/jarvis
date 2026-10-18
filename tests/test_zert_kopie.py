#!/usr/bin/env python3
"""Waechter: Zertifikate landen als root in certs/, ohne Symlinks zu folgen
(Code-Review 2026-10-18).

``certbot_obtain`` und sein Renewal-Hook schrieben als root mit cp/chmod/chown
in ``certs/`` – ein Verzeichnis des Dienstbenutzers. Ein Symlink
``server.key -> <fremde Datei>`` liess root das Ziel ueberschreiben und dem
Dienstbenutzer geben.

  [1] ``backend/broker/zert_kopie.kopieren`` AUSGEFUEHRT im Wegwerf-
      Verzeichnis: Inhalt + Modus, Symlink an Zielstelle wird ERSETZT (Ziel
      unberuehrt), ``certs`` selbst als Symlink wird abgewiesen.
  [2] Op und Hook (Syntaxbaum/Text des erzeugten Hooks): die Op ruft
      ``zert_kopie.kopieren``, kein ``copy2``/``os.chown`` mehr; der Hook ruft
      das Skript aus CODE_ROOT, kein ``cp``/``chown``.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


try:
    from backend.broker import zert_kopie as ZK
except Exception as e:  # noqa: BLE001
    abbruch("zert_kopie nicht importierbar: %s" % e)

SK = Path(tempfile.mkdtemp(prefix="zert_kopie_"))
uid, gid = os.getuid(), os.getgid()
try:
    le = SK / "live" / "jarvis.beispiel.de"
    le.mkdir(parents=True)
    (le / "fullchain.pem").write_text("KETTE")
    (le / "privkey.pem").write_text("SCHLUESSEL")
    certs = SK / "projekt" / "certs"
    certs.mkdir(parents=True)

    print("\n[1] kopieren()")
    erg = ZK.kopieren("jarvis.beispiel.de", str(certs), uid, gid, quelle_dir=str(le))
    check("(Positivkontrolle) beide Dateien abgelegt", sorted(erg) == ["server.crt", "server.key"], str(erg))
    if FAIL:
        abbruch("Messaufbau traegt nicht")
    check("Inhalt stimmt", (certs / "server.crt").read_text() == "KETTE"
          and (certs / "server.key").read_text() == "SCHLUESSEL")
    check("server.key 0600, server.crt 0644",
          stat.S_IMODE((certs / "server.key").stat().st_mode) == 0o600
          and stat.S_IMODE((certs / "server.crt").stat().st_mode) == 0o644)

    opfer = SK / "fremd.txt"
    opfer.write_text("UNBERUEHRT")
    os.chmod(opfer, 0o640)
    (certs / "server.key").unlink()
    (certs / "server.key").symlink_to(opfer)
    ZK.kopieren("jarvis.beispiel.de", str(certs), uid, gid, quelle_dir=str(le))
    check("Symlink server.key -> fremde Datei: das ZIEL bleibt unberuehrt", opfer.read_text() == "UNBERUEHRT")
    check("... Modus des Ziels unveraendert", stat.S_IMODE(opfer.stat().st_mode) == 0o640)
    check("... und server.key ist jetzt eine echte Datei mit dem Schluessel",
          not (certs / "server.key").is_symlink() and (certs / "server.key").read_text() == "SCHLUESSEL")
    check("keine Temp-Datei bleibt liegen", sorted(p.name for p in certs.iterdir()) == ["server.crt", "server.key"],
          str(sorted(p.name for p in certs.iterdir())))

    anders = SK / "anderswo"
    anders.mkdir()
    shutil.rmtree(certs)
    certs.symlink_to(anders)
    try:
        ZK.kopieren("jarvis.beispiel.de", str(certs), uid, gid, quelle_dir=str(le))
        wurf = False
    except OSError:
        wurf = True
    check("certs selbst als Symlink: abgewiesen", wurf is True)
    check("... und nichts im Linkziel abgelegt", list(anders.iterdir()) == [])
    try:
        ZK.kopieren("x; rm -rf /", str(anders), uid, gid, quelle_dir=str(le))
        wurf = False
    except ValueError:
        wurf = True
    check("ungueltige Domain abgewiesen", wurf is True)
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n[2] Op und Hook")
quelle = (ROOT / "backend" / "broker" / "ops.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)
fn = next((n for n in baum.body if isinstance(n, ast.FunctionDef) and n.name == "_op_certbot_obtain"), None)
if fn is None:
    abbruch("_op_certbot_obtain nicht gefunden")
rufe = [ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)]
check("Op ruft zert_kopie.kopieren", any(r.endswith("kopieren") for r in rufe), str(rufe))
check("Op ruft kein shutil.copy2 / os.chown / os.chmod auf Dateien mehr",
      not any(r in ("shutil.copy2", "os.chmod") for r in rufe)
      and sum(1 for r in rufe if r == "os.chown") <= 1, str([r for r in rufe if r.startswith(("os.", "shutil."))]))
hook = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and ast.unparse(c.func).endswith("write_text")]
hook_text = ast.unparse(hook[0]) if hook else ""
check("(Positivkontrolle) Hook-Text gefunden", bool(hook_text))
check("Hook ruft zert_kopie.py aus CODE_ROOT", "zert_kopie.py" in ast.unparse(fn) and "CODE_ROOT" in ast.unparse(fn))
check("Hook enthaelt kein cp/chown/chmod mehr",
      not any(w in hook_text for w in ("cp -L", "chown ", "chmod ")), hook_text[:200])

shutil.rmtree(SK, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
