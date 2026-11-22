#!/usr/bin/env python3
"""Waechter: Wissens-Endpunkte und Wissensgraph-Nachlauf halten die Event-Loop frei.

Anlass (ECHT 2026-11-16, gemessen): jede Unterseite brauchte >5 s. Der
Haupt-Thread des Dienstes rechnete alle 2-5 s fuer 0,5-4 s am Stueck und
beantwortete in der Zeit nicht einmal ``/api/health``. Ursachen, beide IN der
Event-Loop:

1. ``faiss_meta.json`` (104 MB, 58.044 Chunks) wurde von ``/api/wissen/scope``
   (ruft jede Portal-Seite), ``/api/knowledge/groups`` und ``/stats`` bei JEDEM
   Abruf neu geparst – gebraucht werden dort nur Pfade und Anzahl.
2. Der Wiki-Sammellauf las und schrieb je erzeugter Seite den ganzen Wiki-Index
   (19 MB, fsync); ebenso die Widerspruchspruefung ihre 22-MB-Ablage.

Abschnitt 1 und 2 fuehren die Caches WIRKLICH aus (Sandkasten), Abschnitt 3
prueft die Event-Loop-Zusagen als REGEL am AST: in den genannten async-Funktionen
wird keine der teuren Funktionen direkt AUFGERUFEN – nur als Argument von
``asyncio.to_thread`` uebergeben.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import quell_ausschnitt  # noqa: E402  (linear statt ast.get_source_segment)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{info}]" if info else ""))


def abbruch(grund):
    print(f"ABBRUCH (Exit 2): {grund}")
    sys.exit(2)


# ─── Sandkasten: backend.config nur als Attrappe (der echte Import schreibt
# die Live-settings.json zurueck) ───────────────────────────────────────────
class _Cfg:
    profiles = []

    def __init__(self):
        self.s = {}

    def get_setting(self, k, d=None):
        return self.s.get(k, d)

    def save_setting(self, k, v):
        self.s[k] = v

    def get_skill_states(self):
        return {}

    def __getattr__(self, n):
        return None


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
sys.modules["backend.config"] = _cfgmod

TMP = Path(tempfile.mkdtemp(prefix="evloop_wissen_"))

# ─── 1. Wiki-Index: einmal parsen je Datei-Stand ─────────────────────────────
print("\n[1] Wiki-Index wird je Datei-Stand nur EINMAL geparst")
try:
    from backend import wissensgraph as wg
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.wissensgraph nicht importierbar: {e}")

wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    abbruch("Sandkasten greift nicht (ORDNER zeigt hinaus)")

_echt_lesen = wg._json_lesen
_parsezahl = {"n": 0}


def _zaehlend(p, vorgabe):
    if Path(p).name == "index.json":
        _parsezahl["n"] += 1
    return _echt_lesen(p, vorgabe)


wg._json_lesen = _zaehlend
try:
    wg.wiki_index_schreiben({"k1": {"datei": "a.md", "quellen": {"x": 1.0}}})
    _parsezahl["n"] = 0
    a = wg.wiki_index_lesen()
    b = wg.wiki_index_lesen()
    check("Positivkontrolle: der Inhalt kommt an", a.get("k1", {}).get("datei") == "a.md", a)
    check("nach eigenem Schreiben wird NICHT neu geparst", _parsezahl["n"] == 0, _parsezahl)
    check("zweites Lesen liefert denselben Stand", a == b)

    # Ein Schreiber am Cache vorbei (Test, Fremdprozess, Umbenennung) muss gesehen werden.
    wg._json_schreiben(wg._o() / "wiki" / "index.json", {"k2": {"datei": "b.md"}})
    c = wg.wiki_index_lesen()
    check("ein Schreiben am Cache VORBEI wird erkannt", "k2" in c and "k1" not in c, c)
    check("…und genau einmal neu geparst", _parsezahl["n"] == 1, _parsezahl)
    wg.wiki_index_lesen()
    check("…danach wieder aus dem Cache", _parsezahl["n"] == 1, _parsezahl)

    # Umlenken des Ordners (Tests) darf nicht den Stand des alten zeigen.
    wg.ORDNER = TMP / "graph2"
    d = wg.wiki_index_lesen()
    check("ein anderer Ablageordner liefert NICHT den alten Stand", d == {}, d)
    wg.ORDNER = TMP / "graph"
finally:
    wg._json_lesen = _echt_lesen

# ─── 2. FAISS-Uebersicht: Pfade/Anzahl ohne Parsen je Abruf ────────────────
print("\n[2] FAISS-Metadaten werden nicht je Abruf geparst")
KNOW = (ROOT / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
kbaum = ast.parse(KNOW)
kfun = {n.name: n for n in ast.walk(kbaum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in ("_faiss_uebersicht", "_faiss_meta_pfad", "_indexed_rel_paths", "get_stats",
             "content_search_paths"):
    if name not in kfun:
        abbruch(f"knowledge.{name} nicht gefunden – Schnitt unmoeglich")

_jsonzahl = {"n": 0}


class _JsonZaehler:
    @staticmethod
    def loads(s, *a, **k):
        _jsonzahl["n"] += 1
        return json.loads(s, *a, **k)

    @staticmethod
    def load(f, *a, **k):
        _jsonzahl["n"] += 1
        return json.load(f, *a, **k)


ns = {"json": _JsonZaehler, "threading": threading, "Path": Path,
      "PROJECT_ROOT": TMP, "_vector_store": None,
      "_faiss_uebersicht_cache": None, "_faiss_uebersicht_lock": threading.Lock()}
code = "\n\n".join(quell_ausschnitt.segment(KNOW, kfun[n]) for n in ("_faiss_meta_pfad", "_faiss_uebersicht"))
exec(compile("from __future__ import annotations\n" + code, "knowledge_schnitt", "exec"), ns)
uebersicht = ns["_faiss_uebersicht"]

meta = TMP / "data" / "vector_store" / "faiss_meta.json"
meta.parent.mkdir(parents=True, exist_ok=True)
meta.write_text(json.dumps([{"file_path": "data/rag/a.md", "text": "x"},
                            {"file_path": "data/rag/a.md", "text": "y"},
                            {"file_path": "data/rag/b.md", "text": "z"}]), encoding="utf-8")
n, pfade = uebersicht()
check("Positivkontrolle: Chunks und Pfade stimmen", n == 3 and pfade == {"data/rag/a.md", "data/rag/b.md"},
      (n, pfade))
uebersicht()
uebersicht()
check("drei Abrufe, EIN Parsen", _jsonzahl["n"] == 1, _jsonzahl)
st = meta.stat()
meta.write_text(json.dumps([{"file_path": "data/rag/c.md", "text": "q"}]), encoding="utf-8")
os.utime(meta, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
n2, p2 = uebersicht()
check("eine geaenderte Datei wird neu gelesen", n2 == 1 and p2 == {"data/rag/c.md"}, (n2, p2))
check("…genau einmal", _jsonzahl["n"] == 2, _jsonzahl)


class _VS:
    def __init__(self):
        self._lock = threading.Lock()
        self._meta = [{"file_path": "data/rag/live.md", "text": "t"}] * 4


ns["_vector_store"] = _VS()
n3, p3 = uebersicht()
check("ist der VectorStore geladen, ist ER die Quelle (kein Dateizugriff)",
      n3 == 4 and p3 == {"data/rag/live.md"} and _jsonzahl["n"] == 2, (n3, p3, _jsonzahl))
ns["_vector_store"] = None
meta.unlink()
check("ohne Datei: leer statt Fehler", uebersicht() == (0, frozenset()))


def _ruft(fn_node, namen):
    """Namen, die im Rumpf als Funktion AUFGERUFEN werden (Name oder Attribut)."""
    raus = set()
    for k in ast.walk(fn_node):
        if isinstance(k, ast.Call):
            f = k.func
            nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if nm in namen:
                raus.add(nm)
    return raus


for name in ("_indexed_rel_paths", "get_stats"):
    treffer = _ruft(kfun[name], {"loads", "load"})
    check(f"knowledge.{name} parst die Metadaten-Datei nicht selbst", not treffer, treffer)
check("Positivkontrolle der Regel: content_search_paths parst im Rueckfall sehr wohl",
      _ruft(kfun["content_search_paths"], {"loads", "load"}) == {"loads"})

# ─── 3. Event-Loop-Regeln am AST ────────────────────────────────────────────
print("\n[3] Teure Arbeit laeuft nicht direkt in der Event-Loop")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
mbaum = ast.parse(MAIN)
mfun = {n.name: n for n in ast.walk(mbaum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

TEUER_MAIN = {"get_stats", "known_paths_with_disk", "_indexed_rel_paths", "_editable_groups_for",
              "list_groups", "ungrouped_files", "_kb_list_subfolders"}
for ep in ("get_knowledge_stats", "knowledge_groups_list", "knowledge_groups_ungrouped", "wissen_scope"):
    node = mfun.get(ep)
    if node is None:
        abbruch(f"Endpunkt {ep} nicht gefunden")
    check(f"{ep} ist async (Positivkontrolle)", isinstance(node, ast.AsyncFunctionDef))
    direkt = _ruft(node, TEUER_MAIN)
    check(f"{ep} ruft nichts Teures direkt", not direkt, direkt)
    check(f"{ep} benutzt asyncio.to_thread", "to_thread" in _ruft(node, {"to_thread"}))
check("Positivkontrolle der Regel: _wissen_scope_daten ruft _editable_groups_for",
      "_wissen_scope_daten" in mfun and "_editable_groups_for" in _ruft(mfun["_wissen_scope_daten"],
                                                                       TEUER_MAIN))

for datei, fname, teuer in (
        ("wissensgraph_wiki.py", "seite_erzeugen",
         {"_vermerken", "_knoten", "_stand", "graph", "_seite_ablegen", "wiki_index_lesen",
          "wiki_index_schreiben"}),
        ("wissensgraph_widerspruch.py", "begriff_pruefen",
         {"_vermerken", "_knoten_suchen", "graph", "widersprueche_lesen", "widersprueche_schreiben"})):
    q = (ROOT / "backend" / datei).read_text(encoding="utf-8")
    fn = next((n for n in ast.walk(ast.parse(q))
               if isinstance(n, ast.AsyncFunctionDef) and n.name == fname), None)
    if fn is None:
        abbruch(f"{datei}::{fname} nicht gefunden")
    direkt = _ruft(fn, teuer)
    check(f"{fname} ruft Ablage/Graph nicht direkt in der Loop", not direkt, direkt)
    uebergeben = {a.id for k in ast.walk(fn) if isinstance(k, ast.Call)
                  and isinstance(k.func, ast.Attribute) and k.func.attr == "to_thread"
                  for a in k.args[:1] if isinstance(a, ast.Name)}
    check(f"Positivkontrolle: {fname} uebergibt _vermerken an to_thread", "_vermerken" in uebergeben,
          uebergeben)

print(f"\nErgebnis: {OK} OK, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
