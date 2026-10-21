#!/usr/bin/env python3
"""Waechter: ein Wurzelordner unter data/rag laesst sich in einen anderen
Wissensordner verschieben und wird dabei zum Unterordner (2026-10-21).

Vorgabe: ``data/rag/beispiel`` -> ``data/rag/Test und Demo/beispiel``.

Gemessen wird die WIRKUNG der echten ``_kb_move_folder`` (per ``ast``
geschnitten, im Sandkasten ausgefuehrt – das Verzeichnis wandert wirklich):
  1. Admin-Weg: Wurzel wandert, wird aus der Ordnerliste ausgetragen, und das
     erst NACH der Relokation des Index.
  2. /wissen-Weg (ohne Schalter): Wurzel bleibt abgewiesen.
  3. Grenzen: Freigabe-Wurzel, Ziel im eigenen Teilbaum, Ziel ausserhalb,
     Spiegel, bestehender Name, laufende Indizierung.
  4. ``knowledge_sync.freigaben_verschieben`` zieht Freigaben praefixsauber mit.
  5. Als REGEL (AST): der Admin-Endpunkt setzt den Schalter, der /wissen-
     Endpunkt nicht; ``relocate_folder_index`` ruft die Freigaben-Relokation.

    python3 tests/test_wurzel_verschieben.py
"""
import ast
import sys
import tempfile
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
KN = (WURZEL / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)

_ok = _fail = 0


def check(text, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  -> {detail}" if detail else ""))


def sicher(fn, info=""):
    """Eine Pruefung darf NICHT werfen – sonst endet der Lauf ohne Bilanz."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        global _fail
        _fail += 1
        print(f"  FAIL {info or 'Aufruf'} wirft: {type(e).__name__}: {e}")
        return None


def knoten(name, baum=BAUM):
    for k in baum.body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return k
    print(f"ABBRUCH – Funktion {name} fehlt (Altstand?)")
    sys.exit(2)


for _n in ("_kb_move_folder", "_kb_norm_rel", "_kb_configured_root_for",
           "_kb_safe_within_data", "move_knowledge_subfolder", "wissen_move_subfolder"):
    knoten(_n)

sys.path.insert(0, str(WURZEL))
try:
    from backend import rag_pfad as _rag            # noqa: E402
    from backend import knowledge_sync as ks_echt    # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)

# ── Sandkasten ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="wurzel-verschieben-"))
if not str(SAND).startswith(tempfile.gettempdir()):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)

TD = "data/rag/Test und Demo"
BSP = "data/rag/beispiel"
LISTE = []          # die "konfigurierte" Ordnerliste
GESPEICHERT = []    # jede gespeicherte Liste
ABLAUF = []         # Reihenfolge: relocate / speichern
SPIEGEL = {"data/rag/spiegel"}
INDEX_LAEUFT = [False]


def aufbauen():
    import shutil
    shutil.rmtree(SAND / "data", ignore_errors=True)
    for p in (f"{TD}/nxREHA", f"{BSP}/unter", "data/rag/spiegel", "data/rag/andere", "data/fremd",
              "data/alt", f"{TD}/zurueck/tief", f"{TD}/_kein_wurzelname", f"{TD}/andere"):
        (SAND / p).mkdir(parents=True, exist_ok=True)
    (SAND / BSP / "datei.md").write_text("x")
    (SAND / TD / "zurueck" / "z.md").write_text("z")
    LISTE[:] = [TD, BSP, "data/rag/spiegel", "data/rag/andere", "/mnt/rag/share_0", "data/alt"]
    GESPEICHERT.clear()
    ABLAUF.clear()


wissensmod = types.ModuleType("backend.tools.knowledge")
wissensmod.PROJECT_ROOT = SAND
wissensmod.get_index_progress = lambda: {"running": INDEX_LAEUFT[0]}


def _relocate(alt, neu):
    ABLAUF.append(("relocate", str(alt), str(neu)))
    return {"vector_chunks": 7}


wissensmod.relocate_folder_index = _relocate
sys.modules["backend.tools.knowledge"] = wissensmod

ksmod = types.ModuleType("backend.knowledge_sync")
ksmod.schreibsperre = lambda p: "Spiegel" if any(
    p == s or p.startswith(s + "/") for s in SPIEGEL) else ""
sys.modules["backend.knowledge_sync"] = ksmod
import backend  # noqa: E402
backend.knowledge_sync = ksmod


SPEICHERN_KLAPPT = [True]


def _speichern(liste):
    ABLAUF.append(("speichern",))
    if not SPEICHERN_KLAPPT[0]:
        return False
    GESPEICHERT.append(list(liste))
    LISTE[:] = list(liste)
    return True


NS = {"Path": Path, "_rag": _rag, "_KB_FOLDER_NAME_RE": None,
      "_kb_current_folder_list": lambda: list(LISTE),
      "_kb_save_folder_list": _speichern}
# Namensregel der Anlage: die ECHTE Regex aus main.py, nicht nachgebaut.
for _k in BAUM.body:
    if isinstance(_k, ast.Assign) and any(getattr(t, "id", "") == "_KB_FOLDER_NAME_RE" for t in _k.targets):
        exec("import re\n" + ast.get_source_segment(MAIN, _k), NS)
if NS["_KB_FOLDER_NAME_RE"] is None:
    print("ABBRUCH – _KB_FOLDER_NAME_RE nicht gefunden")
    sys.exit(2)
for _n in ("_kb_norm_rel", "_kb_configured_root_for", "_kb_safe_within_data",
           "_kb_validate_folder_name", "_kb_move_folder"):
    exec(ast.get_source_segment(MAIN, knoten(_n)), NS)
# _kb_safe_within_data prueft gegen backend.tools.knowledge.PROJECT_ROOT -> Sandkasten
schieben = NS["_kb_move_folder"]


print("=" * 72)
print("0. POSITIVKONTROLLE – Unterordner verschieben geht wie bisher")
print("=" * 72)
aufbauen()
r = sicher(lambda: schieben(f"{BSP}/unter", TD), "Unterordner")
check("Unterordner wandert (Bestand)", r is not None and r[1] is None and (SAND / TD / "unter").is_dir(), r)
check("… Ordnerliste unberuehrt", GESPEICHERT == [], GESPEICHERT)
if _fail:
    print("\nABBRUCH – Positivkontrolle fehlgeschlagen")
    sys.exit(2)

print("\n1. Admin-Weg: Wurzel wird Unterordner")
aufbauen()
r = sicher(lambda: schieben(BSP, TD, wurzel_erlaubt=True), "Wurzel")
res, err, code = r if r else (None, "wirft", 0)
check("Antwort 200 ohne Fehler", err is None and code == 200, (err, code))
check("Verzeichnis liegt jetzt unter dem Ziel",
      (SAND / TD / "beispiel" / "datei.md").is_file() and not (SAND / BSP).exists())
check("Antwort nennt neuen Pfad und was_root",
      bool(res) and res.get("path") == f"{TD}/beispiel" and res.get("was_root") is True, res)
check("Wurzel aus der Ordnerliste ausgetragen, Rest unveraendert",
      LISTE == [TD, "data/rag/spiegel", "data/rag/andere", "/mnt/rag/share_0", "data/alt"], LISTE)
check("Index wird VOR dem Austragen relokalisiert",
      [a[0] for a in ABLAUF] == ["relocate", "speichern"], ABLAUF)
# Ueber Gleichheit des ganzen Tupels, nicht ueber Indizes: ein [1] auf einen
# Eintrag anderer Form WIRFT, und der Lauf endete ohne Bilanz (Gegenprobe).
check("Relokation mit den richtigen Pfaden",
      ("relocate", str(SAND / BSP), str(SAND / TD / "beispiel")) in ABLAUF, ABLAUF)

print("\n2. /wissen-Weg: ohne Schalter bleibt die Wurzel abgewiesen")
aufbauen()
r = sicher(lambda: schieben(BSP, TD), "ohne Schalter")
check("400 und nichts bewegt", bool(r) and r[2] == 400 and (SAND / BSP).is_dir() and not ABLAUF, r)

print("\n3. Grenzen")
aufbauen()
r = sicher(lambda: schieben("/mnt/rag/share_0", TD, wurzel_erlaubt=True), "Freigabe")
check("Freigabe-Wurzel unter /mnt: abgewiesen", bool(r) and r[1] is not None and not ABLAUF, r)
# ⚠ Dieser Fall traegt die Pruefung "direkt unter data/rag" ALLEIN: /mnt
#   scheitert zusaetzlich an _kb_safe_within_data, eine Wurzel unter data/
#   nicht. Ohne ihn waere die Pruefung in der Gegenprobe stumm.
r = sicher(lambda: schieben("data/alt", TD, wurzel_erlaubt=True), "data/alt")
check("Wurzel unter data/, aber nicht unter data/rag: 400, nichts bewegt",
      bool(r) and r[2] == 400 and (SAND / "data/alt").is_dir() and not ABLAUF, r)
r = sicher(lambda: schieben(BSP, f"{BSP}/unter", wurzel_erlaubt=True), "in sich")
check("in den eigenen Teilbaum: 400", bool(r) and r[2] == 400 and (SAND / BSP).is_dir(), r)
r = sicher(lambda: schieben(BSP, "data/fremd", wurzel_erlaubt=True), "fremd")
check("Ziel ausserhalb jedes Wissensordners: 404", bool(r) and r[2] == 404, r)
r = sicher(lambda: schieben("data/rag/spiegel", TD, wurzel_erlaubt=True), "Spiegel")
check("Spiegel-Wurzel: 409", bool(r) and r[2] == 409 and (SAND / "data/rag/spiegel").is_dir(), r)
r = sicher(lambda: schieben("data/rag/andere", TD, wurzel_erlaubt=True), "Konflikt")
check("gleichnamiger Ordner im Ziel: 409, Liste unveraendert",
      bool(r) and r[2] == 409 and "data/rag/andere" in LISTE and not GESPEICHERT, r)
INDEX_LAEUFT[0] = True
r = sicher(lambda: schieben(BSP, TD, wurzel_erlaubt=True), "Index")
INDEX_LAEUFT[0] = False
check("laufende Indizierung: 409, nichts bewegt", bool(r) and r[2] == 409 and (SAND / BSP).is_dir(), r)

print("\n3b. Gegenrichtung: Unterordner wird eigener Wissensordner (Ziel data/rag)")
aufbauen()
r = sicher(lambda: schieben(f"{TD}/zurueck", "data/rag", wurzel_erlaubt=True), "zur Wurzel")
res, err, code = r if r else (None, "wirft", 0)
check("200, now_root", err is None and bool(res) and res.get("now_root") is True
      and res.get("path") == "data/rag/zurueck", r)
check("Verzeichnis liegt jetzt direkt unter data/rag",
      (SAND / "data/rag/zurueck/tief").is_dir() and (SAND / "data/rag/zurueck/z.md").is_file()
      and not (SAND / TD / "zurueck").exists())
check("in die Ordnerliste eingetragen", "data/rag/zurueck" in LISTE, LISTE)
check("ERST eingetragen, DANN relokalisiert", [a[0] for a in ABLAUF] == ["speichern", "relocate"], ABLAUF)
aufbauen()
r = sicher(lambda: schieben(f"{TD}/zurueck", "data/rag"), "ohne Schalter")
check("/wissen (ohne Schalter): data/rag ist kein Ziel, nichts bewegt",
      bool(r) and r[2] == 404 and (SAND / TD / "zurueck").is_dir() and not ABLAUF, r)
r = sicher(lambda: schieben(f"{TD}/_kein_wurzelname", "data/rag", wurzel_erlaubt=True), "Name")
check("Name, den die Anlage ablehnt: 400, nichts bewegt",
      bool(r) and r[2] == 400 and (SAND / TD / "_kein_wurzelname").is_dir() and not ABLAUF, r)
r = sicher(lambda: schieben(f"{TD}/andere", "data/rag", wurzel_erlaubt=True), "Konflikt")
check("gleichnamige Wurzel vorhanden: 409", bool(r) and r[2] == 409 and not ABLAUF, r)
r = sicher(lambda: schieben("data/rag/andere", "data/rag", wurzel_erlaubt=True), "schon Wurzel")
check("Wurzel nach data/rag: 400 (liegt schon dort)", bool(r) and r[2] == 400, r)
SPEICHERN_KLAPPT[0] = False
r = sicher(lambda: schieben(f"{TD}/zurueck", "data/rag", wurzel_erlaubt=True), "Speichern scheitert")
SPEICHERN_KLAPPT[0] = True
check("Liste nicht speicherbar: 500, Verzeichnis zurueck, Index unberuehrt",
      bool(r) and r[2] == 500 and (SAND / TD / "zurueck/z.md").is_file()
      and not (SAND / "data/rag/zurueck").exists()
      and not any(a[0] == "relocate" for a in ABLAUF), (r, ABLAUF))

print("\n4. Freigaben ziehen mit (knowledge_sync.freigaben_verschieben)")
ks_echt._state = {"shares": [{"folder": BSP}, {"folder": f"{BSP}/unter"},
                             {"folder": "data/rag/beispiel2"}, {"folder": TD}],
                  "peers": []}
ks_echt._speichern = lambda: None      # Sandkasten: nichts auf die Platte
n = sicher(lambda: ks_echt.freigaben_verschieben(BSP, f"{TD}/beispiel"), "freigaben")
ordner = [s["folder"] for s in ks_echt._state["shares"]]
check("zwei Freigaben umgeschrieben", n == 2, n)
check("Wurzel und Unterordner zeigen auf den neuen Ort",
      ordner[:2] == [f"{TD}/beispiel", f"{TD}/beispiel/unter"], ordner)
check("Praefix-Nachbar 'beispiel2' bleibt", ordner[2] == "data/rag/beispiel2", ordner)
check("fremde Freigabe bleibt", ordner[3] == TD, ordner)

print("\n5. REGEL (AST)")


def schalter(funk):
    for n in ast.walk(knoten(funk)):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_kb_move_folder":
            return {k.arg: getattr(k.value, "value", None) for k in n.keywords}
    return None


check("Admin-Endpunkt setzt wurzel_erlaubt=True",
      (schalter("move_knowledge_subfolder") or {}).get("wurzel_erlaubt") is True)
w = schalter("wissen_move_subfolder")
check("/wissen-Endpunkt setzt den Schalter NICHT", w is not None and "wurzel_erlaubt" not in w, w)
reloc = knoten("relocate_folder_index", ast.parse(KN))
check("relocate_folder_index ruft freigaben_verschieben",
      any(isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "freigaben_verschieben"
          for n in ast.walk(reloc)))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
