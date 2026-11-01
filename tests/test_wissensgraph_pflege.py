#!/usr/bin/env python3
"""Wissensgraph: Pflege folgt dem Vektorindex – ohne neue Extraktion.

Ausgefuehrt mit den ECHTEN ``VectorStore``-Methoden (ohne faiss: das Objekt
entsteht ohne ``__init__``, nur ``_rebuild``/``_save``/``_vectors_at`` sind
ersetzt – die Pflegemethoden selbst und ihre Hooks laufen unveraendert):
  1. ``remove_files``/``remove_path_prefix`` entfernen die Quellen im Graphen.
  2. ``rename_file_path``/``rename_path_prefix`` verschieben NUR Metadaten:
     Inhalt und Zeitpunkt der Quelle bleiben, kein Modellaufruf.
  3. Praefix mit Trenner (share_1 trifft share_10 nicht).
  4. REGEL am AST: der Indexlauf reiht nach ``add_chunks`` ein und ruft
     nirgends eine Extraktion; der Vormerk-Helfer ruft nur ``einreihen``.

    python3 tests/test_wissensgraph_pflege.py
"""
import ast
import json
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(name, cond, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


def section(t):
    print("\n" + t)


class _Cfg:
    profiles = []

    def get_setting(self, k, d=None):
        return d

    def __getattr__(self, n):
        return None


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
sys.modules["backend.config"] = _cfgmod

try:
    from backend import wissensgraph as wg
    from backend import wissensgraph_extraktion as wgx
    from backend.tools import vector_store as vsm
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)
if not hasattr(vsm, "_graph_melden") or not hasattr(vsm.VectorStore, "chunks_fuer"):
    print("ABBRUCH – vector_store ohne Graph-Hooks (Altstand?)")
    sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="wg_pflege_"))
wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)

# Jeder Modellaufruf waere hier ein Fehler: Pflege extrahiert nie.
_modellaufrufe = []


async def _kein_modell(*a, **k):
    _modellaufrufe.append(a)
    raise AssertionError("Modellaufruf in der Pflege")

wgx.modell_aufruf = _kein_modell

R = str(wg.PROJECT_ROOT)


def vs_mit(pfade):
    v = object.__new__(vsm.VectorStore)
    v._lock = threading.Lock()
    v._meta = [{"file_path": p, "mtime": 5.0, "chunk_index": i, "text": f"t{i}"}
               for p in pfade for i in range(2)]
    v._gen = 0
    v._save = lambda: None
    v._vectors_at = lambda idx: list(idx)

    def _rebuild(meta, vecs, save=True):
        v._meta = meta
    v._rebuild = _rebuild
    return v


def graph_mit(*pfade):
    d = wg._o() / "quellen"
    if d.is_dir():
        for f in d.glob("*.json"):
            f.unlink()
    wg._zuruecksetzen_fuer_test()
    for p in pfade:
        wg.quelle_schreiben(p, 5.0, [{"name": "E " + Path(p).stem, "typ": "system",
                                      "beschreibung": "x"}], [])


def bestand():
    return sorted(wg.quellen_index())


A, B, C = R + "/data/rag/a/x.md", R + "/data/rag/a/y.md", R + "/data/rag/b/z.md"

section("1. Entfernen folgt dem Vektorindex")
graph_mit(A, B, C)
vs = vs_mit([A, B, C])
check("Positivkontrolle: drei Quellen im Graphen", len(bestand()) == 3, str(bestand()))
n = vs.remove_files([A])
check("remove_files: Index meldet die entfernten Chunks", n == 2, str(n))
check("remove_files: Quelle im Graphen weg, die anderen bleiben",
      bestand() == ["data/rag/a/y.md", "data/rag/b/z.md"], str(bestand()))
vs.remove_file(B)
check("remove_file (Einzeldatei) wirkt ebenso", bestand() == ["data/rag/b/z.md"], str(bestand()))
graph_mit(A, B, C)
vs = vs_mit([A, B, C])
vs.remove_path_prefix(R + "/data/rag/a")
check("remove_path_prefix: der ganze Ordner geht, der Nachbar bleibt",
      bestand() == ["data/rag/b/z.md"], str(bestand()))
wg.einreihen(C, 9.0)
vs.remove_files([C])
check("Entfernen nimmt auch den Warteschlangen-Eintrag mit", wg.warteschlange_laenge() == 0)

section("2. Umbenennen verschiebt nur Metadaten")
graph_mit(A, C)
vor = wg.quelle_lesen(A)
vs = vs_mit([A, C])
wg.einreihen(A, 5.0)
vs.rename_file_path(A, R + "/data/rag/a/neu.md")
nach = wg.quelle_lesen(R + "/data/rag/a/neu.md")
check("rename_file_path: Quelle unter dem neuen Pfad", nach is not None and wg.quelle_lesen(A) is None)
check("Inhalt unveraendert (Entitaeten, mtime)",
      nach is not None and nach["entitaeten"] == vor["entitaeten"] and nach["mtime"] == vor["mtime"])
check("Zeitpunkt unveraendert = keine neue Extraktion",
      nach is not None and nach["zeitpunkt"] == vor["zeitpunkt"])
check("Warteschlangen-Eintrag zieht mit", [m for m, _ in wg.warteschlange()] == ["data/rag/a/neu.md"],
      str(wg.warteschlange()))
wg.warteschlange_leeren()
graph_mit(A, B, C)
vs = vs_mit([A, B, C])
vs.rename_path_prefix(R + "/data/rag/a", R + "/data/rag/neu")
check("rename_path_prefix: beide Dateien des Ordners ziehen um",
      bestand() == ["data/rag/b/z.md", "data/rag/neu/x.md", "data/rag/neu/y.md"], str(bestand()))
check("kein Modellaufruf in der ganzen Pflege", _modellaufrufe == [], str(len(_modellaufrufe)))

section("3. Praefix mit Trenner")
S1, S10 = R + "/data/rag/share_1/x.md", R + "/data/rag/share_10/y.md"
graph_mit(S1, S10)
vs = vs_mit([S1, S10])
vs.rename_path_prefix(R + "/data/rag/share_1", R + "/data/rag/share_2")
check("rename share_1 laesst share_10 stehen",
      bestand() == ["data/rag/share_10/y.md", "data/rag/share_2/x.md"], str(bestand()))
vs.remove_path_prefix(R + "/data/rag/share_1")
check("remove share_1 laesst share_10 stehen", "data/rag/share_10/y.md" in bestand(), str(bestand()))

section("4. chunks_fuer liefert die Eingabe aus dem Index")
vs = vs_mit([A])
vs._meta.reverse()
ch, mt = vs.chunks_fuer(A)
check("Chunks in Reihenfolge des chunk_index, mit mtime", ch == ["t0", "t1"] and mt == 5.0, f"{ch} {mt}")
check("unbekannte Datei: leer, None", vs.chunks_fuer(R + "/data/rag/q.md") == ([], None))

section("5. REGEL: der Indexlauf reiht nur ein")
KSRC = (ROOT / "backend/tools/knowledge.py").read_text(encoding="utf-8")
KB = ast.parse(KSRC)


def fn(baum, name):
    return next((n for n in ast.walk(baum) if isinstance(n, ast.FunctionDef) and n.name == name), None)


def namen_gerufen(knoten):
    raus = []
    for n in ast.walk(knoten):
        if isinstance(n, ast.Call):
            f = n.func
            raus.append(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return raus


lauf = fn(KB, "_vector_index_lauf")
check("Positivkontrolle: _vector_index_lauf gefunden", lauf is not None)
if lauf is None:
    print("ABBRUCH – Funktion nicht gefunden, die Regeln waeren trivial")
    sys.exit(2)
# Im selben Block wie add_chunks, und DANACH
treffer = False
for n in ast.walk(lauf):
    for feld in ("body", "orelse"):
        block = getattr(n, feld, None)
        if not isinstance(block, list):
            continue
        idx_add = [i for i, s in enumerate(block) if "add_chunks" in namen_gerufen(s)]
        idx_rein = [i for i, s in enumerate(block) if "_graph_einreihen" in namen_gerufen(s)
                    and not isinstance(s, (ast.If, ast.For, ast.Try, ast.With))]
        if idx_add and idx_rein and min(idx_rein) > min(idx_add):
            treffer = True
check("nach add_chunks folgt im selben Block _graph_einreihen", treffer)
check("am Laufende wird die Schlange gesichert",
      "_graph_einreihen_abschliessen" in namen_gerufen(lauf))
# Reihenfolge auf der obersten Ebene des Laufs: das Einreihen kommt NACH der
# Gruppenzuordnung, sonst sieht der Arbeiter eine neue Datei "ausserhalb" ihrer
# Gruppe und wirft sie aus der Schlange.
pos_zuordnen = [i for i, st in enumerate(lauf.body) if "automatisch_zuordnen" in namen_gerufen(st)]
pos_schluss = [i for i, st in enumerate(lauf.body) if "_graph_einreihen_abschliessen" in namen_gerufen(st)]
check("Einreihen erst NACH der Gruppenzuordnung",
      bool(pos_zuordnen) and bool(pos_schluss) and min(pos_schluss) > max(pos_zuordnen),
      f"zuordnen {pos_zuordnen}, schluss {pos_schluss}")
VERBOTEN = {"extrahiere_datei", "modell_aufruf", "eine_datei_bearbeiten", "dauerlauf",
            "generate_response"}
check("_vector_index_lauf ruft keine Extraktion", not (set(namen_gerufen(lauf)) & VERBOTEN))
helfer = fn(KB, "_graph_einreihen")
check("_graph_einreihen merkt nur vor (kein einreihen, keine Extraktion)",
      helfer is not None and "einreihen" not in namen_gerufen(helfer)
      and "append" in namen_gerufen(helfer) and not (set(namen_gerufen(helfer)) & VERBOTEN))
schluss = fn(KB, "_graph_einreihen_abschliessen")
check("_graph_einreihen_abschliessen reiht ein, sichert, weckt – und extrahiert nicht",
      schluss is not None and {"einreihen", "warteschlange_sichern", "wecken"} <= set(namen_gerufen(schluss))
      and not (set(namen_gerufen(schluss)) & VERBOTEN))

VSRC = ast.parse((ROOT / "backend/tools/vector_store.py").read_text(encoding="utf-8"))
for meth, hook in (("remove_files", "pflege_entfernt"), ("remove_path_prefix", "pflege_praefix_entfernt"),
                   ("rename_file_path", "pflege_umbenannt"),
                   ("rename_path_prefix", "pflege_praefix_umbenannt")):
    f = fn(VSRC, meth)
    rufe = [n for n in ast.walk(f) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_graph_melden"] if f else []
    konst = [r.args[0].value for r in rufe if r.args and isinstance(r.args[0], ast.Constant)]
    check(f"VectorStore.{meth} meldet {hook}", konst == [hook], str(konst))
    check(f"Hook in {meth} steht AUSSERHALB des Locks",
          f is not None and not any(isinstance(w, ast.With) and any(r in ast.walk(w) for r in rufe)
                                    for w in ast.walk(f)))
check("die gemeldeten Funktionen gibt es im Graphen",
      all(hasattr(wg, h) for h in ("pflege_entfernt", "pflege_praefix_entfernt",
                                   "pflege_umbenannt", "pflege_praefix_umbenannt")))

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
