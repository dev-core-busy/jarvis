#!/usr/bin/env python3
"""Waechter: Pfad-Traversal beim Wissens-Upload (Befund B1, 2026-11).

``target / file.filename`` schrieb mit ``../../x.py`` oder einem absoluten
Namen AUSSERHALB des Wissensordners (.py/.sh sind erlaubte Endungen –
Codeausfuehrung nach dem Neustart). Gemessen wird die WIRKUNG: die beiden
ECHTEN Endpunkt-Funktionen (``upload_knowledge_files``, ``wissen_upload``)
werden per AST aus ``backend/main.py`` geschnitten und mit Attrappen ihrer
Umgebung in einem Sandkasten ausgefuehrt. Danach wird das Dateisystem
gezaehlt: liegt irgendetwas ausserhalb des Zielordners?

Dazu ``_kb_unpack_zip`` (ZIP-Zweig, Zip-Slip) gegen dieselbe Frage.
Kein ``backend.config``. Exit 0 gruen, 1 FAIL, 2 konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import io
import os
import sys
import tempfile
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
MAIN = ROOT / "backend" / "main.py"

OK = FAIL = 0


def check(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


QUELLE = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
NAMEN_FN = {"upload_knowledge_files", "wissen_upload", "_upload_dateiname",
            "_upload_ziel", "_kb_unpack_zip", "_zip_entry_name"}
NAMEN_VAR = {"_ZIP_MAX_TOTAL_BYTES", "_ZIP_MAX_ENTRIES", "_ZIP_MAX_DEPTH",
             "_ZIP_MIN_FREE_BYTES", "_ZIP_SKIP_DIRS"}
teile = []
gefunden = set()
for knoten in BAUM.body:
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)) and knoten.name in NAMEN_FN:
        knoten.decorator_list = []
        teile.append(knoten)
        gefunden.add(knoten.name)
    elif isinstance(knoten, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in NAMEN_VAR for t in knoten.targets):
        teile.append(knoten)
        gefunden.update(t.id for t in knoten.targets if isinstance(t, ast.Name))
fehlt = (NAMEN_FN | NAMEN_VAR) - gefunden
if fehlt:
    print("ABBRUCH: in main.py nicht gefunden: %s" % sorted(fehlt), flush=True)
    sys.exit(2)

SANDKASTEN = Path(tempfile.mkdtemp(prefix="upload_pfad_"))
PROJ = SANDKASTEN / "proj"
ZIEL = PROJ / "data" / "rag" / "ordner"
ZIEL.mkdir(parents=True)
DRAUSSEN = SANDKASTEN / "draussen"
DRAUSSEN.mkdir()
(DRAUSSEN / "opfer.txt").write_text("unveraendert", encoding="utf-8")
(ZIEL / "link.txt").symlink_to(DRAUSSEN / "opfer.txt")
(ZIEL / "tot.txt").symlink_to(DRAUSSEN / "tot_ziel.txt")   # verwaister Symlink
if not str(SANDKASTEN).startswith(tempfile.gettempdir()):
    print("ABBRUCH: Sandkasten liegt nicht unter dem Temp-Verzeichnis", flush=True)
    sys.exit(2)


# ── Attrappen der Umgebung ─────────────────────────────────────────────────
class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


class UploadFile:
    def __init__(self, filename, daten):
        self.filename = filename
        self._d = daten
        self.file = io.BytesIO(daten)

    async def read(self):
        return self._d


def _stub(name, **attr):
    m = types.ModuleType(name)
    m.__dict__.update(attr)
    sys.modules[name] = m
    return m


_stub("backend.license_enforce", darf_wissen_hinzufuegen=lambda n: (True, ""))
_stub("backend.knowledge_groups", set_assignment=lambda *a, **k: None)
_stub("backend.tools.knowledge", _get_folders=lambda: [ZIEL], PROJECT_ROOT=PROJ,
      alle_endungen=lambda: {".txt", ".py", ".sh", ".pdf", ".md"},
      invalidate_files_cache=lambda: None)
_stub("backend.config")   # nie echt laden

REL = str(ZIEL.relative_to(PROJ))
NS = {
    "Path": Path, "JSONResponse": JSONResponse, "UploadFile": UploadFile,
    "Request": object, "File": lambda *a, **k: None, "Form": lambda *a, **k: None,
    "Depends": lambda *a, **k: None, "require_knowledge_editor": None,
    "require_auth": None, "_kb_mirror_guard": lambda f: None,
    "_kb_configured_root_for": lambda f: REL, "_kb_safe_within_data": lambda f: True,
    "_kb_norm_rel": lambda f: f, "_wissen_check_groups": lambda u, g: (True, ""),
    "_editable_groups_for": lambda u: [], "_wissen_unter": lambda a, b: True,
    "_wissen_allowed_folders": lambda u, g: [], "_aktivitaet": lambda *a, **k: None,
    "_may_edit_knowledge": lambda u: False, "_run_cancellable": None,
    "_norm_login": lambda u: u, "config": None,
}
modul = ast.Module(body=teile, type_ignores=[])
exec(compile(modul, str(MAIN), "exec"), NS)


def bestand():
    """Alle Dateien unter dem Sandkasten (relativ), ohne den Symlink selbst."""
    raus = set()
    for wurzel, _dirs, dateien in os.walk(SANDKASTEN):
        for d in dateien:
            raus.add(str((Path(wurzel) / d).relative_to(SANDKASTEN)))
    return raus


VORHER = bestand()
ABS = str(DRAUSSEN / "absolut.py")
BOESE = ["../../../draussen/ausbruch.py", ABS, "..\\..\\..\\draussen\\win.sh",
         "link.txt", "tot.txt"]
LEER = ["", ".", "..", ".versteckt.txt", "a/..", "x\x00y.txt"]


def lauf(endpunkt, namen):
    """Ein Absturz des Endpunkts ist ein FAIL der Zusage, kein Abbruch des
    Waechters (Register: eine Sabotage, die den Waechter abstuerzen laesst,
    hat nicht gebissen) – er kommt als ``absturz`` zurueck."""
    try:
        return _lauf(endpunkt, namen)
    except Exception as e:  # noqa: BLE001
        return {"absturz": repr(e)}


def _lauf(endpunkt, namen):
    files = [UploadFile(n, ("inhalt-%d" % i).encode()) for i, n in enumerate(namen)]
    if endpunkt == "knowledge":
        r = asyncio.run(NS["upload_knowledge_files"](files=files, folder=REL,
                                                     groups="", user="u"))
    else:
        r = asyncio.run(NS["wissen_upload"](request=None, files=files, folder=REL,
                                            groups="", gen_questions="", job_id="",
                                            user="u"))
    return r.content


try:
    for ep in ("knowledge", "wissen"):
        print("\n%s/upload" % ep)
        # Positivkontrolle: der Weg schreibt ueberhaupt in den Zielordner
        r = lauf(ep, ["normal_%s.txt" % ep])
        if not (ZIEL / ("normal_%s.txt" % ep)).is_file():
            print("ABBRUCH: Positivkontrolle – normaler Upload kam nicht an (%r)" % r,
                  flush=True)
            sys.exit(2)
        check(r.get("total_saved") == 1, "Positivkontrolle: normaler Upload gespeichert")

        r = lauf(ep, BOESE)
        check("absturz" not in r, "boese Namen: kein Absturz (%s)" % r.get("absturz", ""))
        neu = bestand() - VORHER
        draussen = sorted(p for p in neu if not p.startswith("proj/data/rag/ordner/"))
        check(not draussen, "nichts ausserhalb des Zielordners geschrieben %s" % draussen)
        check((DRAUSSEN / "opfer.txt").read_text(encoding="utf-8") == "unveraendert",
              "Symlink im Zielordner wurde nicht durchschrieben")
        check(not Path(ABS).exists(), "absoluter Name schreibt nicht an seinen Ort")
        check(not (DRAUSSEN / "tot_ziel.txt").exists(),
              "verwaister Symlink im Zielordner wurde nicht durchschrieben")
        namen = {s["name"] for s in r.get("saved", [])}
        check(any(n.startswith("ausbruch") for n in namen),
              "../-Name landet als reiner Basisname IM Ordner")
        check(any(n.startswith("win") and n.endswith(".sh") for n in namen),
              "Windows-Pfad (Backslash) landet als Basisname IM Ordner")
        check(all("/" not in n and "\\" not in n for n in namen),
              "gespeicherte Namen tragen keinen Pfadanteil")

        r = lauf(ep, LEER)
        check("absturz" not in r, "leere Namen: kein Absturz (%s)" % r.get("absturz", ""))
        check(r.get("total_saved") == 0 and r.get("total_rejected") == len(LEER),
              "leere/Punkt-/versteckte/Steuerzeichen-Namen abgewiesen (%s gespeichert)"
              % r.get("total_saved"))
        VORHER = bestand()

    print("\nHilfsfunktionen direkt")
    f = NS["_upload_dateiname"]
    check(f("../../a.py") == "a.py", "_upload_dateiname: ../ entfernt")
    check(f("C:\\x\\b.txt") == "b.txt", "_upload_dateiname: Windows-Pfad")
    check(f(None) is None, "_upload_dateiname: None abgewiesen")
    check(f("/") is None, "_upload_dateiname: nur Trenner abgewiesen")
    z = NS["_upload_ziel"](ZIEL, "link.txt")
    check(z is None or (z.name != "link.txt" and not z.is_symlink()),
          "_upload_ziel schreibt nie durch einen Symlink gleichen Namens (%s)" % z)
    (ZIEL / "verwaist.txt").symlink_to(DRAUSSEN / "gibtsnicht.txt")
    check(NS["_upload_ziel"](ZIEL, "verwaist.txt") is None,
          "_upload_ziel lehnt einen VERWAISTEN Symlink ab (exists() sieht ihn nicht)")
    check(NS["_upload_ziel"](ZIEL, "frei.txt") == ZIEL / "frei.txt",
          "_upload_ziel: freier Name bleibt")

    print("\nZIP-Zweig (_kb_unpack_zip)")
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("../../../draussen/zipslip.py", "x")
        z.writestr("/abs/zipabs.py", "x")
        z.writestr("unter/ok.txt", "x")
    vor = bestand()
    geschrieben, abgelehnt, _n = NS["_kb_unpack_zip"](puffer.getvalue(), ZIEL,
                                                      {".txt", ".py"}, min_free_bytes=None)
    neu = bestand() - vor
    check(neu == {"proj/data/rag/ordner/unter/ok.txt"},
          "ZIP: nur der harmlose Eintrag geschrieben (%s)" % sorted(neu))
    check(len(abgelehnt) == 2, "ZIP: ../ und absoluter Eintrag abgelehnt (%s)" % abgelehnt)
finally:
    import shutil
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n" + "=" * 60)
print("  %d OK, %d FAIL" % (OK, FAIL))
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
