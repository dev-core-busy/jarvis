#!/usr/bin/env python3
"""Waechter: der Vision-Skill laedt face_recognition auch ohne pkg_resources.

WARUM (2026-10-29): setuptools >= 82 liefert pkg_resources nicht mehr mit,
Jarvis braucht aber >= 84.1.0 (PYSEC-2026-3447, GHSA-xmj3-9gf7-h52w).
face_recognition_models 0.3.0 – die letzte Fassung – importiert
`from pkg_resources import resource_filename`; fehlt das, ruft face_recognition
`quit()`. vision_engine stellt deshalb waehrend des Imports einen Ersatz bereit
(`_pkg_resources_ersatz`) und faengt SystemExit mit ab.

Gemessen wird die WIRKUNG, je Fall in einem eigenen Prozess (sys.modules und
sys.path sind danach unberuehrt): vision_engine.py wird echt geladen, neben
nachgebauten Paketen face_recognition / face_recognition_models, die sich so
verhalten wie die echten (Modellpfad beim Import, `quit()` bei Fehlschlag).
cv2/numpy sind Attrappen – vision_engine braucht sie beim Laden nur als Namen.

Faelle:
  fehlt          pkg_resources nicht auffindbar (find_spec -> None, wie ab 82)
  gesperrt       die Suche selbst wirft ImportError (zweiter Zweig)
  vorhanden      ein echtes pkg_resources liegt bereit -> KEIN Ersatz
  geladen        pkg_resources steht schon in sys.modules (ohne __spec__) ->
                 KEIN Ersatz, und es bleibt danach stehen
  modelle_fehlen face_recognition ruft quit() -> None, Prozess lebt weiter
  ohne_paket     face_recognition gar nicht installiert -> None
  echt           (nur wo installiert) die ECHTEN Pakete mit gesperrtem
                 pkg_resources; auf DEV mit venv/bin/python laufen lassen

Positivkontrollen je Fall: die Ausgangslage ist wirklich hergestellt (das
Kind meldet, ob pkg_resources vor dem Laden auffindbar war). Fehlt sie: Exit 2.

Lauf:  python3 tests/test_vision_pkg_ersatz.py
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUELLE = ROOT / "skills" / "vision" / "vision_engine.py"
MODELL = "models/dlib_face_recognition_resnet_model_v1.dat"

MODELLE_PAKET = '''\
from pkg_resources import resource_filename

def face_recognition_model_location():
    return resource_filename(__name__, "%s")
''' % MODELL

# Wie face_recognition/api.py: Import mit quit() im Fehlerfall, Modellpfad beim Laden.
FR_PAKET = '''\
try:
    import face_recognition_models
except Exception:
    print("FR_QUIT")
    quit()
MODELLPFAD = face_recognition_models.face_recognition_model_location()
'''

ECHTES_PKG = '''\
ECHT = True
def resource_filename(paket, ressource):
    return "ECHT:" + ressource
'''


# ── Kindprozess ──────────────────────────────────────────────────────────────

class _Sperre:
    """meta_path-Finder, der jede Suche nach pkg_resources mit ImportError beantwortet."""

    def find_spec(self, name, path=None, target=None):
        if name == "pkg_resources" or name.startswith("pkg_resources."):
            raise ModuleNotFoundError("pkg_resources gesperrt (Probe)")
        return None


def kind(fall: str, wurzel: str) -> None:
    import importlib.util
    import types

    if fall != "echt":
        # Ohne site-packages: kein fremdes pkg_resources, kein echtes face_recognition.
        sys.path[:] = [p for p in sys.path
                       if not p.rstrip("/").endswith(("site-packages", "dist-packages"))]
        sys.path.insert(0, wurzel)
        # Nur ohne die echten Pakete: face_recognition/dlib brauchen echtes numpy.
        # vision_engine nennt np.ndarray in Annotationen auf Modulebene.
        for mod in ("cv2", "numpy"):
            sys.modules.setdefault(mod, types.ModuleType(mod))
        sys.modules["numpy"].ndarray = object
    if fall in ("gesperrt", "modelle_fehlen", "echt"):
        sys.meta_path.insert(0, _Sperre())
    if fall == "geladen":
        # Schon importiert und ohne __spec__: find_spec wirft dann ValueError.
        geladen = types.ModuleType("pkg_resources")
        geladen.__spec__ = None
        geladen.resource_filename = lambda paket, ressource: "GELADEN:" + ressource
        sys.modules["pkg_resources"] = geladen

    try:
        vorher = importlib.util.find_spec("pkg_resources") is not None
    except ImportError:
        vorher = False
    except ValueError:
        vorher = True     # steht in sys.modules, nur ohne __spec__
    erg = {"pkg_vorher": vorher}
    try:
        spec = importlib.util.spec_from_file_location("vision_engine_probe", str(QUELLE))
        ve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ve)
    except BaseException as e:  # noqa: BLE001 – auch SystemExit soll gemeldet werden
        erg["absturz"] = "%s: %s" % (type(e).__name__, e)
        print("ERGEBNIS " + json.dumps(erg))
        return
    fr = ve.face_recognition
    erg["fr_none"] = fr is None
    erg["pkg_danach"] = "pkg_resources" in sys.modules
    if fall == "echt" and fr is not None:
        import face_recognition_models as frm
        pfade = [frm.pose_predictor_model_location(), frm.pose_predictor_five_point_model_location(),
                 frm.face_recognition_model_location(), frm.cnn_face_detector_model_location()]
        erg["modellpfade"] = pfade
        erg["modelle_da"] = all(os.path.isfile(p) for p in pfade)
    elif fr is not None:
        erg["modellpfad"] = getattr(fr, "MODELLPFAD", None)
    print("ERGEBNIS " + json.dumps(erg))


# ── Elternprozess ────────────────────────────────────────────────────────────

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name}" + (f"  ({detail})" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


def baue(wurzel: Path, modelle: bool, fr: bool, echtes_pkg: bool) -> Path:
    if modelle:
        p = wurzel / "face_recognition_models"
        (p / "models").mkdir(parents=True)
        (p / "__init__.py").write_text(MODELLE_PAKET, encoding="utf-8")
        (p / MODELL).write_bytes(b"modell")
    if fr:
        (wurzel / "face_recognition").mkdir()
        (wurzel / "face_recognition" / "__init__.py").write_text(FR_PAKET, encoding="utf-8")
    if echtes_pkg:
        (wurzel / "pkg_resources.py").write_text(ECHTES_PKG, encoding="utf-8")
    return wurzel / "face_recognition_models" / MODELL


def starte(fall: str, wurzel: Path, python: str = sys.executable) -> tuple[dict, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([python, str(Path(__file__).resolve()), "--kind", fall, str(wurzel)],
                       capture_output=True, text=True, timeout=300, env=env, cwd=str(wurzel))
    zeilen = [z for z in r.stdout.splitlines() if z.startswith("ERGEBNIS ")]
    if r.returncode != 0 or len(zeilen) != 1:
        abbruch("Kind '%s' rc=%s: %s" % (fall, r.returncode, (r.stdout + r.stderr).strip()[-400:]))
    erg = json.loads(zeilen[0][len("ERGEBNIS "):])
    # Nur SystemExit ist ein Befund (der quit()-Weg) – jeder andere Absturz
    # heisst, dass der Messaufbau nicht traegt, und wuerde sonst als FAIL zaehlen.
    if erg.get("absturz") and not erg["absturz"].startswith("SystemExit"):
        abbruch("Kind '%s': %s" % (fall, erg["absturz"]))
    return erg, r.stdout


def main() -> int:
    if not QUELLE.is_file():
        abbruch(f"{QUELLE} fehlt")
    tmp = Path(tempfile.mkdtemp(prefix="vis_pkg_"))
    try:
        print("[1] pkg_resources fehlt (find_spec -> None, wie ab setuptools 82)")
        w = tmp / "fehlt"; w.mkdir()
        datei = baue(w, modelle=True, fr=True, echtes_pkg=False)
        e, _ = starte("fehlt", w)
        if e.get("pkg_vorher"):
            abbruch("pkg_resources trotz entfernter site-packages auffindbar")
        check("Laden stuerzt nicht ab", "absturz" not in e, e.get("absturz", ""))
        check("face_recognition ist geladen", e.get("fr_none") is False, e)
        check("Modellpfad zeigt auf die Datei im Paket",
              e.get("modellpfad") == str(datei.resolve()), e.get("modellpfad"))
        check("Ersatz nach dem Import wieder entfernt", e.get("pkg_danach") is False, e)

        print("\n[2] Suche nach pkg_resources wirft ImportError")
        w = tmp / "gesperrt"; w.mkdir()
        datei = baue(w, modelle=True, fr=True, echtes_pkg=False)
        e, _ = starte("gesperrt", w)
        if e.get("pkg_vorher"):
            abbruch("Sperre wirkt nicht")
        check("face_recognition ist geladen", e.get("fr_none") is False, e)
        check("Modellpfad zeigt auf die Datei im Paket",
              e.get("modellpfad") == str(datei.resolve()), e.get("modellpfad"))
        check("Ersatz nach dem Import wieder entfernt", e.get("pkg_danach") is False, e)

        print("\n[3] echtes pkg_resources vorhanden -> kein Ersatz")
        w = tmp / "vorhanden"; w.mkdir()
        baue(w, modelle=True, fr=True, echtes_pkg=True)
        e, _ = starte("vorhanden", w)
        if not e.get("pkg_vorher"):
            abbruch("das bereitgelegte pkg_resources ist nicht auffindbar")
        check("face_recognition ist geladen", e.get("fr_none") is False, e)
        check("das echte resource_filename wurde benutzt",
              e.get("modellpfad") == "ECHT:" + MODELL, e.get("modellpfad"))

        print("\n[3b] pkg_resources schon geladen (ohne __spec__) -> kein Ersatz")
        w = tmp / "geladen"; w.mkdir()
        baue(w, modelle=True, fr=True, echtes_pkg=False)
        e, _ = starte("geladen", w)
        check("das geladene resource_filename wurde benutzt",
              e.get("modellpfad") == "GELADEN:" + MODELL, e.get("modellpfad"))
        check("das geladene Modul bleibt stehen", e.get("pkg_danach") is True, e)

        print("\n[4] face_recognition ruft quit() (Modelle fehlen)")
        w = tmp / "modelle_fehlen"; w.mkdir()
        baue(w, modelle=False, fr=True, echtes_pkg=False)
        e, aus = starte("modelle_fehlen", w)
        if "FR_QUIT" not in aus:
            abbruch("der quit()-Zweig der Attrappe lief nicht")
        check("SystemExit beendet das Laden nicht", "absturz" not in e, e.get("absturz", ""))
        check("face_recognition ist None", e.get("fr_none") is True, e)

        print("\n[5] face_recognition nicht installiert")
        w = tmp / "ohne_paket"; w.mkdir()
        e, _ = starte("ohne_paket", w)
        check("Laden stuerzt nicht ab", "absturz" not in e, e.get("absturz", ""))
        check("face_recognition ist None", e.get("fr_none") is True, e)

        print("\n[6] echte Pakete mit gesperrtem pkg_resources")
        import importlib.util
        if importlib.util.find_spec("face_recognition") is None:
            print("  (uebersprungen: face_recognition hier nicht installiert – "
                  "auf DEV mit venv/bin/python laufen lassen)")
        else:
            w = tmp / "echt"; w.mkdir()
            e, _ = starte("echt", w)
            if e.get("pkg_vorher"):
                abbruch("Sperre wirkt nicht")
            check("Laden stuerzt nicht ab", "absturz" not in e, e.get("absturz", ""))
            check("face_recognition ist geladen", e.get("fr_none") is False, e)
            check("alle vier Modelldateien vorhanden", e.get("modelle_da") is True,
                  e.get("modellpfade"))
            check("Ersatz nach dem Import wieder entfernt", e.get("pkg_danach") is False, e)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nErgebnis: {ok} OK, {fail} FAIL")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--kind":
        kind(sys.argv[2], sys.argv[3])
        sys.exit(0)
    sys.exit(main())
