#!/usr/bin/env python3
"""Waechter: atomares JSON und fail-closed Lesen (Code-Review 2026-10-18).

  [1] ``backend.atomar`` AUSGEFUEHRT im Wegwerf-Verzeichnis: Inhalt, Modus,
      Sicherung, Temp-Datei, Symlink wird ersetzt statt durchschrieben,
      kaputte Datei -> Sicherung, beides kaputt -> Unlesbar, Fehler beim
      Ersetzen laesst das Original stehen.
  [2] ``knowledge_groups``: eine KAPUTTE Manifestdatei liefert NICHT mehr die
      Vorgabe – ein Schreibvorgang danach haette sonst alle Zuordnungen
      geloescht. Mit Sicherung bleiben sie erhalten.
  [3] REGEL: die auf ``atomar`` umgestellten Module schreiben ihre Zustandsdatei
      nicht mehr per ``write_text`` (Syntaxbaum).
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import json
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


try:
    from backend import atomar as A
    from backend import knowledge_groups as KG
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: nicht importierbar: %s" % e)
    sys.exit(2)

SK = Path(tempfile.mkdtemp(prefix="atomar_"))
try:
    print("\n[1] atomar")
    p = SK / "z.json"
    A.schreiben(p, {"a": 1})
    check("(Positivkontrolle) geschrieben und gelesen", A.lesen(p) == {"a": 1})
    if FAIL:
        print("ABBRUCH: Messaufbau traegt nicht")
        sys.exit(2)
    os.chmod(p, 0o640)
    A.schreiben(p, {"a": 2})
    check("Modus des Vorgaengers bleibt", stat.S_IMODE(p.stat().st_mode) == 0o640)
    bak = SK / "z.json.bak"
    check("Sicherung traegt den vorigen Stand", bak.exists() and json.loads(bak.read_text()) == {"a": 1})
    check("keine Temp-Datei", sorted(x.name for x in SK.iterdir()) == ["z.json", "z.json.bak"])
    p.write_text("{halb")
    try:
        _st = A.lesen(p)
    except A.Unlesbar:
        _st = None
    check("kaputte Datei -> Sicherung", _st == {"a": 1}, str(_st))
    (SK / "z.json.bak").write_text("auch kaputt")
    try:
        A.lesen(p)
        wurf = False
    except A.Unlesbar:
        wurf = True
    check("beides kaputt -> Unlesbar (keine stille Vorgabe)", wurf)
    check("fehlende Datei -> Vorgabe", A.lesen(SK / "fehlt.json", vorgabe=lambda: {"v": 1}) == {"v": 1})
    try:
        A.schreiben(SK / "f.json", [1], sicherung=False)
        A.lesen(SK / "f.json", pruefen=lambda d: isinstance(d, dict))
        wurf = False
    except A.Unlesbar:
        wurf = True
    check("Liste statt Objekt ohne Sicherung -> Unlesbar", wurf)
    opfer = SK / "opfer"
    opfer.write_text("SYSTEM")
    link = SK / "l.json"
    link.symlink_to(opfer)
    A.schreiben(link, {"x": 1})
    check("Symlink: Ziel unberuehrt, Eintrag ersetzt", opfer.read_text() == "SYSTEM" and not link.is_symlink())
    echt = os.replace
    try:
        A.os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("Probe"))
        try:
            A.schreiben(SK / "z2.json", {"n": 1})
        except OSError:
            pass
    finally:
        A.os.replace = echt
    check("Fehler beim Ersetzen: keine Temp-Datei bleibt",
          not any(x.name.startswith(".z2.json") for x in SK.iterdir()))

    print("\n[2] knowledge_groups")
    KG.MANIFEST_PATH = SK / "kb" / ".groups.json"
    d = KG.load()
    d["assignments"]["data/rag/a.pdf"] = ["ibs"]
    with KG._lock:
        KG._save_unlocked(d)
    with KG._lock:
        KG._save_unlocked(KG._load_unlocked())     # zweiter Stand -> Sicherung entsteht
    check("(Positivkontrolle) Zuordnung gespeichert", KG.load()["assignments"].get("data/rag/a.pdf") == ["ibs"])
    KG.MANIFEST_PATH.write_text("{abgeschnitten")
    check("kaputtes Manifest: Zuordnungen aus der Sicherung, NICHT die Vorgabe",
          KG.load()["assignments"].get("data/rag/a.pdf") == ["ibs"])
    (KG.MANIFEST_PATH.with_name(".groups.json.bak")).write_text("kaputt")
    try:
        KG.load()
        wurf = False
    except A.Unlesbar:
        wurf = True
    check("Manifest und Sicherung kaputt: Unlesbar statt leerer Vorgabe", wurf)
    check("... und die kaputte Datei bleibt fuer die Reparatur stehen",
          KG.MANIFEST_PATH.read_text() == "{abgeschnitten")
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n[3] Regel: umgestellte Module schreiben nicht per write_text")
for modul, name in (("backend/knowledge_groups.py", "_save_unlocked"),):
    baum = ast.parse((ROOT / modul).read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(baum) if isinstance(n, ast.FunctionDef) and n.name == name), None)
    rufe = [ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)] if fn else []
    check("%s:%s nutzt atomar.schreiben, kein write_text" % (modul, name),
          fn is not None and any(r.endswith("schreiben") for r in rufe)
          and not any(r.endswith("write_text") for r in rufe), str(rufe))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
