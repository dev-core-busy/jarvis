#!/usr/bin/env python3
"""Waechter: Vision-Profilnamen koennen den Gesichter-Ordner nicht verlassen.

BEFUND (2026-10-11, beim Abarbeiten von BSI H4): der Profilname ist zugleich
der Verzeichnisname unter data/vision/faces/ und wurde NIRGENDS geprueft –
weder in den Endpunkten noch in der Engine. `delete_profile("../..")` haette
per shutil.rmtree ausserhalb von faces/ geloescht, `rename_profile` ein
Verzeichnis beliebig verschoben, `start_training` eines angelegt. Erreichbar
war das auch ueber die LLM-Werkzeuge (vision_profiles delete/rename,
vision_train) – also ueber Prompt-Injektion.

Gemessen wird die WIRKUNG: die echten Methoden laufen (per AST aus
vision_engine.py geschnitten – cv2/numpy werden dafuer nicht gebraucht)
gegen einen Sandkasten, in dem NEBEN faces/ ein Opfer-Ordner liegt. Danach
muss der Opfer-Ordner unversehrt sein. Positivkontrolle: ein gueltiger Name
wird wirklich angelegt, umbenannt und geloescht – sonst waere „nichts
passiert" trivial wahr.

Lauf:  python3 tests/test_vision_profilname.py
"""
import ast
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
QUELLE = ROOT / "skills" / "vision" / "vision_engine.py"

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  \u2705 {name}")
    else:
        fail += 1
        print(f"  \u274c {name}" + (f" \u2013 {detail}" if detail else ""))


src = QUELLE.read_text(encoding="utf-8")
baum = ast.parse(src)

# Modulweite Bausteine der Namensregel
modul_teile = []
for knoten in baum.body:
    if isinstance(knoten, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_PROFILNAME" for t in knoten.targets):
        modul_teile.append(ast.get_source_segment(src, knoten))
    if isinstance(knoten, ast.FunctionDef) and knoten.name == "profilname_gueltig":
        modul_teile.append(ast.get_source_segment(src, knoten))

klasse = next((k for k in baum.body
               if isinstance(k, ast.ClassDef) and k.name == "VisionEngine"), None)
METHODEN = ("_profil_dir", "start_training", "delete_profile", "rename_profile",
            "get_thumbnail", "_compute_encodings", "list_profiles")
methoden = {}
if klasse:
    for k in klasse.body:
        if isinstance(k, ast.FunctionDef) and k.name in METHODEN:
            methoden[k.name] = ast.get_source_segment(src, k)

fehlt = [m for m in METHODEN if m not in methoden]
if len(modul_teile) != 2 or fehlt:
    print(f"ABBRUCH: Bausteine fehlen (Modul: {len(modul_teile)}/2, Methoden: {fehlt})")
    sys.exit(2)

import textwrap  # noqa: E402

klassentext = "class E:\n" + "\n".join(
    textwrap.indent(textwrap.dedent(m), "    ") for m in methoden.values())
ns = {"re": re, "Path": Path, "Optional": Optional, "shutil": shutil, "os": os,
      "DEFAULT_SAMPLES": 30, "face_recognition": None,
      "log": type("L", (), {"info": staticmethod(lambda *a, **k: None),
                            "warning": staticmethod(lambda *a, **k: None)})()}
exec("\n".join(modul_teile) + "\n" + klassentext, ns)
E = ns["E"]
gueltig = ns["profilname_gueltig"]

tmp = Path(tempfile.mkdtemp(prefix="vis_profil_"))
try:
    faces = tmp / "data" / "vision" / "faces"
    faces.mkdir(parents=True)
    opfer = tmp / "data" / "wichtig"
    opfer.mkdir()
    (opfer / "bleibt.txt").write_text("x")
    (faces / "anna").mkdir()
    (faces / "anna" / "001.jpg").write_bytes(b"jpg")

    def neu():
        e = E()
        e.faces_dir = faces
        e._config = {"profiles": {"anna": {"name": "Anna"}, "../../wichtig": {"name": "X"}}}
        e._known_encodings = {}
        e._save_config = lambda: None
        e._save_encodings = lambda: None
        e._running = True
        e._training_active = False
        e._training_name = ""
        return e

    def sicher(f, *a):
        """Ein Wurf (z. B. rmtree auf einen Symlink) ist ein Ergebnis, kein
        Abbruch – sonst endet der Lauf ohne Bilanzzeile."""
        try:
            return f(*a)
        except Exception as ex:  # noqa: BLE001
            return f"WURF: {type(ex).__name__}: {ex}"

    def opfer_heil():
        return opfer.is_dir() and (opfer / "bleibt.txt").is_file()

    print("\n0. Sandkasten")
    check("Opfer-Ordner liegt NEBEN faces/ (nicht darin)",
          opfer.resolve().parent == faces.resolve().parent.parent)
    check("Sandkasten liegt unter /tmp", str(tmp).startswith(tempfile.gettempdir()))

    print("\n1. Die Namensregel")
    for n in ["anna", "max_mueller", "max-m", "max.m", "Jürgen", "a" * 64, "_training_x1"]:
        check(f"gueltig: {n[:20]!r}", gueltig(n))
    for n in ["", "..", "../x", "a/b", "a\\b", ".hidden", "a..b", "-x", "a" * 65,
              "a\nb", "a b", None, 5, "/abs"]:
        check(f"ungueltig: {str(n)[:20]!r}", not gueltig(n))

    print("\n2. delete_profile: kein rmtree ausserhalb von faces/")
    for boes in ["../../wichtig", "../wichtig", str(opfer), "..", "."]:
        r = sicher(neu().delete_profile, boes)
        check(f"delete({boes[-20:]!r}) laesst den Opfer-Ordner stehen", opfer_heil(), r)
    check("faces/ selbst steht noch", faces.is_dir() and (faces / "anna").is_dir())

    print("\n3. rename_profile: weder Quelle noch Ziel ausserhalb")
    r = sicher(neu().rename_profile, "../../wichtig", "neu")
    check("rename(../../wichtig → neu) verschiebt das Opfer nicht",
          opfer_heil() and not (faces / "neu").exists(), r)
    r = sicher(neu().rename_profile, "anna", "../../weg")
    check("rename(anna → ../../weg) verschiebt nicht nach aussen",
          (faces / "anna").is_dir() and not (tmp / "data" / "weg").exists(), r)

    print("\n4. start_training: kein Verzeichnis ausserhalb")
    r = str(sicher(neu().start_training, "../../angelegt"))
    check("start_training(../../angelegt) legt nichts an",
          not (tmp / "data" / "angelegt").exists() and not (tmp / "angelegt").exists(), r)
    check("… und meldet einen Fehler", r.startswith("Fehler"), r)

    print("\n5. get_thumbnail / _compute_encodings lesen nichts ausserhalb")
    opfer.mkdir(exist_ok=True)   # eine Sabotage oben kann ihn geloescht haben
    (opfer / "bleibt.txt").write_text("x")
    (opfer / "001.jpg").write_bytes(b"geheim")
    check("get_thumbnail(../../wichtig) liefert nichts",
          sicher(neu().get_thumbnail, "../../wichtig") is None)

    print("\n6. Symlink im faces/-Ordner, der nach aussen zeigt")
    faces.mkdir(parents=True, exist_ok=True)   # nach einer Sabotage neu aufbauen
    opfer.mkdir(exist_ok=True)
    (opfer / "bleibt.txt").write_text("x")
    (faces / "anna").mkdir(exist_ok=True)
    (faces / "anna" / "001.jpg").write_bytes(b"jpg")
    (faces / "link").symlink_to(opfer, target_is_directory=True)
    check("⚠ get_thumbnail(link → aussen) liest NICHT ausserhalb",
          sicher(neu().get_thumbnail, "link") is None)
    check("_profil_dir(link → aussen) ist None", neu()._profil_dir("link") is None)
    r = sicher(neu().delete_profile, "link")
    check("delete(link → aussen) loescht das Ziel nicht", opfer_heil(), r)
    check("… und wirft nicht (sauberer Fehlertext)", not str(r).startswith("WURF"), r)

    print("\n6b. Die Namensregel wirkt auch dort, wo resolve() nichts merkt")
    # resolve() faengt jeden AUSBRUCH; die Regel haelt zusaetzlich versteckte
    # und options-aehnliche Ordner aus faces/ heraus (".x" und "-x" liegen
    # direkt darunter und wuerden von resolve() angenommen).
    for n in [".versteckt", "-rf", "a b"]:
        check(f"_profil_dir({n!r}) ist None", neu()._profil_dir(n) is None)

    print("\n7. Positivkontrolle: gueltige Namen funktionieren")
    e = neu()
    r = e.start_training("Max Muster")
    check("start_training('Max Muster') legt faces/max_muster an",
          (faces / "max_muster").is_dir(), r)
    e._config["profiles"]["max_muster"] = {"name": "Max Muster"}
    r = e.rename_profile("max_muster", "max_m")
    check("rename(max_muster → max_m) verschiebt", (faces / "max_m").is_dir()
          and not (faces / "max_muster").exists(), r)
    r = e.delete_profile("max_m")
    check("delete(max_m) loescht", not (faces / "max_m").exists(), r)
    check("get_thumbnail('anna') liefert das Bild", e.get_thumbnail("anna") == b"jpg")
    profile = {p["id"]: p for p in neu().list_profiles()}
    check("list_profiles zaehlt Bilder bei gueltigem Namen",
          profile.get("anna", {}).get("num_images") == 1, str(profile.get("anna")))
    check("list_profiles uebersteht einen ungueltigen Bestandsnamen",
          profile.get("../../wichtig", {}).get("num_images") == 0,
          str(profile.get("../../wichtig")))
    check("Opfer-Ordner zum Schluss unversehrt", opfer_heil())
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
