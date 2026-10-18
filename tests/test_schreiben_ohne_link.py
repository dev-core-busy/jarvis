#!/usr/bin/env python3
"""Waechter: root schreibt im Projektbaum nicht durch Symlinks (Code-Review 2026-10-18).

Der Projektbaum gehoert dem Dienstbenutzer. Zwei Stellen liefen dort als root
(Broker) und folgten einem Link:
  * ``config._write_preserve_owner`` (settings.json): ``write_text`` +
    ``os.chown`` auf den Pfad – zudem nicht atomar.
  * ``sandbox_guard.setup`` Schritt 2: ``f.chmod(0o600)`` auf .env/settings.json.

  [1] ``_write_preserve_owner`` AUSGEFUEHRT (per AST geschnitten, ohne
      backend.config zu importieren – der echte Import schreibt die
      Live-settings.json): Inhalt, Modus bleibt, Symlink wird ERSETZT statt
      durchschrieben, keine Temp-Datei, Fehler beim Ersetzen laesst das
      Original stehen.
  [2] ``sandbox_guard``: Schritt 2 setzt die Rechte ueber ``os.open(...,
      O_NOFOLLOW)`` + ``fchmod`` (Syntaxbaum), und ein ``.chmod(`` gibt es dort nicht.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import os
import shutil
import stat
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


baum = ast.parse((ROOT / "backend" / "config.py").read_text(encoding="utf-8"))
fn = [n for n in baum.body if isinstance(n, ast.FunctionDef) and n.name == "_write_preserve_owner"]
if len(fn) != 1:
    abbruch("_write_preserve_owner nicht eindeutig")
ns = {"os": os, "_stat": stat, "threading": threading, "Path": Path}
exec(compile(ast.fix_missing_locations(ast.Module(body=fn, type_ignores=[])), "config", "exec"), ns)
schreib = ns["_write_preserve_owner"]

SK = Path(tempfile.mkdtemp(prefix="ohne_link_"))
try:
    print("\n[1] _write_preserve_owner")
    p = SK / "settings.json"
    schreib(p, '{"a": 1}')
    check("(Positivkontrolle) neue Datei geschrieben", p.read_text() == '{"a": 1}')
    if FAIL:
        abbruch("Messaufbau traegt nicht")
    os.chmod(p, 0o640)
    schreib(p, '{"a": 2}')
    check("Inhalt ersetzt", p.read_text() == '{"a": 2}')
    check("Modus bleibt (0640)", stat.S_IMODE(p.stat().st_mode) == 0o640, oct(stat.S_IMODE(p.stat().st_mode)))
    opfer = SK / "opfer.conf"
    opfer.write_text("SYSTEM")
    os.chmod(opfer, 0o644)
    p.unlink()
    p.symlink_to(opfer)
    schreib(p, '{"b": 1}')
    check("Symlink: das Linkziel bleibt UNBERUEHRT", opfer.read_text() == "SYSTEM")
    check("... Modus des Ziels unveraendert", stat.S_IMODE(opfer.stat().st_mode) == 0o644)
    check("... settings.json ist jetzt eine echte Datei", not p.is_symlink() and p.read_text() == '{"b": 1}')
    check("keine Temp-Datei bleibt liegen", sorted(x.name for x in SK.iterdir()) == ["opfer.conf", "settings.json"],
          str(sorted(x.name for x in SK.iterdir())))
    echt_replace = os.replace

    def _kaputt(*a, **k):
        raise OSError("Platte voll (Probe)")
    import types as _types
    ns["os"] = _types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    ns["os"].replace = _kaputt
    try:
        schreib(p, '{"c": 1}')
        wurf = False
    except OSError:
        wurf = True
    finally:
        ns["os"] = os
    check("Fehler beim Ersetzen: Ausnahme statt stiller Erfolg", wurf is True)
    check("... das Original steht unveraendert", p.read_text() == '{"b": 1}')
    check("... und die Temp-Datei ist weg", sorted(x.name for x in SK.iterdir()) == ["opfer.conf", "settings.json"],
          str(sorted(x.name for x in SK.iterdir())))
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n[2] sandbox_guard: Rechte ohne Link-Folgen")
sg = ast.parse((ROOT / "backend" / "sandbox_guard.py").read_text(encoding="utf-8"))
setup = next((n for n in sg.body if isinstance(n, ast.FunctionDef) and n.name == "setup"), None)
if setup is None:
    abbruch("sandbox_guard.setup nicht gefunden")
schleifen = [n for n in ast.walk(setup) if isinstance(n, ast.For)
             and "_secret_files" in ast.unparse(n.iter)]
check("(Positivkontrolle) Schleife ueber _secret_files() gefunden", len(schleifen) == 1)
if schleifen:
    rumpf = ast.unparse(schleifen[0])
    check("os.open mit O_NOFOLLOW", "os.open(" in rumpf and "O_NOFOLLOW" in rumpf)
    check("fchmod am Deskriptor", "os.fchmod(" in rumpf)
    check("kein .chmod( auf den Pfad", ".chmod(" not in rumpf.replace("os.fchmod(", ""))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
