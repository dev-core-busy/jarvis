#!/usr/bin/env python3
"""Wissensgraph: fragebezogenes Relevanzmodell und vierter Suchkanal.

Ausgefuehrt gegen einen Sandkasten-Graphen und einen VectorStore ohne faiss
(die Kanalfunktionen sind ersetzt, die Fusion selbst laeuft echt):
  1. Fragebegriffe: ein Begriff zaehlt nur, wenn JEDES Wort seines Namens in
     der Frage steht (Beugung toleriert, kurze Woerter nur woertlich); Hubs und
     reine Fuellwoerter nie.
  2. Score = Summe der Seltenheit ln(1 + N/df) der getroffenen Begriffe – der
     Sollwert ist hier von Hand gerechnet, nicht aus dem Modul. Startdokumente
     stehen nicht im Ergebnis.
  3. ⚠ FILTER IN DER ABFRAGE: nur erlaubte Dokumente zaehlen – als Kandidat
     UND in der Seltenheit.
  4. Vierter Kanal: Startdokumente aus der vorlaeufigen Fusion, die FRAGE geht
     an das Modell, hoechstens zwei Chunks je Dokument, Reihenfolge nach
     Graph-Rang, Erlaubnis gilt auch hier, Kanalgewicht 0,5 in der Fusion, ein
     Fehler des Graphen kippt die Suche nicht; ohne Schalter ist die Suche
     unveraendert.
  5. Schalter ``expansion``: Vorgabe AUS; aus = kein Kanal, kein Block.
  6. ``zusammenhaenge``: nur Kanten zwischen Begriffen der Trefferdokumente,
     belegt durch ein erlaubtes Dokument.

    python3 tests/test_wissensgraph_relevanz.py
"""
import math
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

try:
    from backend import wissensgraph as wg
    from backend import wissensgraph_extraktion as wgx
    from backend.tools import knowledge as kn
    from backend.tools import vector_store as vsm
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)
for n in ("relevanz", "frage_begriffe", "zusammenhaenge", "HUB_ANTEIL"):
    if not hasattr(wg, n):
        print(f"ABBRUCH – wissensgraph.{n} fehlt")
        sys.exit(2)
if not hasattr(vsm.VectorStore, "_graph_kanal") or not hasattr(kn, "_graph_rangliste"):
    print("ABBRUCH – Graph-Kanal nicht eingebaut")
    sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="wg_rel_"))
wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)


def ent(n, typ="system"):
    return {"name": n, "typ": typ, "beschreibung": ""}


def rel(a, b):
    return {"von": a, "nach": b, "art": "nutzt"}


# S = Start, traegt A–B (fuer die Zusammenhaenge). "Rechnungsfreigabe" steht in
# D1 und D2 (df 2), "Kostenstelle" nur in D3 (df 1), "SAP" in D1, der Hub H in
# allen, "Kostenstelle Nord" (zwei Woerter) in D4, der reine Fuellwort-Begriff
# "Was" in D4. F0..F5 machen H zum Hub.
S, D1, D2, D3, D4 = (f"data/rag/t/{x}.md" for x in ("s", "d1", "d2", "d3", "d4"))
wg.quelle_schreiben(S, 1, [ent("A"), ent("B"), ent("H"), ent("Rechnungsfreigabe", "prozess")],
                    [rel("A", "B")])
wg.quelle_schreiben(D1, 1, [ent("Rechnungsfreigabe", "prozess"), ent("SAP"), ent("H")], [])
wg.quelle_schreiben(D2, 1, [ent("A"), ent("C"), ent("H"), ent("Rechnungsfreigabe", "prozess")],
                    [rel("A", "C")])
wg.quelle_schreiben(D3, 1, [ent("C"), ent("E"), ent("H"), ent("Kostenstelle", "konzept")], [rel("C", "E")])
wg.quelle_schreiben(D4, 1, [ent("Kostenstelle Nord", "ort"), ent("Was", "konzept"), ent("H")], [])
for i in range(6):
    wg.quelle_schreiben(f"data/rag/t/f{i}.md", 1, [ent("H"), ent(f"Z{i}", "ort")], [])
wg._zuruecksetzen_fuer_test()
N = 11                                # Dokumente im Graphen

section("1. Fragebegriffe")
fb = wg.frage_begriffe("Wie laufen Rechnungsfreigaben fuer eine Kostenstelle, und was macht H?")
check("Positivkontrolle: Begriffe gefunden", len(fb) >= 2, fb)
check("Beugung toleriert (Rechnungsfreigaben → Rechnungsfreigabe)", "e:rechnungsfreigabe" in fb, fb)
check("Kostenstelle woertlich", "e:kostenstelle" in fb, fb)
check("mehrteiliger Name nur, wenn JEDES Wort vorkommt (Kostenstelle Nord fehlt)",
      "e:kostenstelle nord" not in fb, fb)
check("Hub zaehlt nie", "e:h" not in fb, fb)
check("reiner Fuellwort-Begriff ('Was') zaehlt nie", "e:was" not in fb, fb)
check("kurzes Wort nur woertlich: 'saps' trifft SAP nicht", "e:sap" not in wg.frage_begriffe("Was kosten saps?"))
check("... woertlich schon", "e:sap" in wg.frage_begriffe("Was kostet SAP?"))
check("Frage ohne Begriff: leer", wg.frage_begriffe("Wie spaet ist es?") == [])

section("2. Score und Startdokumente")
r = {d: (sc, x) for d, sc, x in wg.relevanz("Rechnungsfreigaben fuer die Kostenstelle", [S])}
check("Positivkontrolle: es gibt Ergebnisse", len(r) >= 2, sorted(r))
check("Startdokument steht nicht im Ergebnis (traegt den Begriff aber)", S not in r, sorted(r))
soll_rf, soll_ks = math.log(1 + N / 3), math.log(1 + N / 1)   # df: S, D1, D2 / nur D3
check("Score = ln(1 + N/df), von Hand gerechnet", D1 in r and abs(r[D1][0] - soll_rf) < 1e-3,
      (r.get(D1), soll_rf))
check("seltener Begriff zaehlt mehr: D3 (df 1) vor D1 (df 3)",
      D3 in r and D1 in r and r[D3][0] > r[D1][0] and abs(r[D3][0] - soll_ks) < 1e-3, (r.get(D3), soll_ks))
check("getroffene Begriffe werden mitgeliefert", D3 in r and r[D3][1]["begriffe"] == ["e:kostenstelle"], r.get(D3))
liste = wg.relevanz("Rechnungsfreigaben fuer die Kostenstelle", [S])
check("Reihenfolge: beste zuerst", [d for d, _s, _x in liste][:1] == [D3], liste[:2])
check("Dokument ohne Fragebegriff erscheint nicht (D4)", D4 not in r, sorted(r))
check("absolute Startpfade werden auf die Manifest-Form gebracht",
      {d for d, _s, _x in wg.relevanz("Rechnungsfreigaben fuer die Kostenstelle",
                                       [str(wg.PROJECT_ROOT / S)])} == set(r))

section("3. Filter in der Abfrage")
erlaubt = {S, D1, D4}                 # D2, D3 fehlen
r2 = {d: sc for d, sc, _x in wg.relevanz("Rechnungsfreigaben fuer die Kostenstelle", [], erlaubt)}
check("Positivkontrolle: ein erlaubtes Dokument kommt weiter", D1 in r2, r2)
check("nicht erlaubte Dokumente erscheinen nicht", D2 not in r2 and D3 not in r2, sorted(r2))
# N = 3 erlaubte Dokumente, df(Rechnungsfreigabe) unter den erlaubten = 2 (S, D1)
soll = math.log(1 + 3 / 2)
check("Seltenheit nur ueber erlaubte Dokumente gerechnet", D1 in r2 and abs(r2[D1] - soll) < 1e-3, (r2.get(D1), soll))
check("Begriff ohne erlaubten Beleg zaehlt nicht (Kostenstelle nur in D3)",
      "e:kostenstelle" not in wg.frage_begriffe("Kostenstelle", erlaubt))

section("4. Zusammenhaenge")
z = wg.zusammenhaenge([S, D2])
check("Kante zwischen Begriffen der Trefferdokumente", any("A ↔ C" in x or "C ↔ A" in x for x in z), z)
check("Hub erscheint nicht", not any(" H " in f" {x} " or x.startswith("H ") for x in z), z)
# A (aus S) und C (aus D3) sind beide erlaubte Treffer-Begriffe – die Kante A–C
# belegt aber NUR D2, und D2 ist nicht erlaubt.
z2 = wg.zusammenhaenge([S, D3], {S, D3})
check("Positivkontrolle: Kante zwischen erlaubten Begriffen erscheint",
      any("C ↔ E" in x or "E ↔ C" in x for x in z2), z2)
check("Kante nur mit erlaubtem Beleg (A–C belegt nur D2)",
      not any("A ↔ C" in x or "C ↔ A" in x for x in z2), z2)

section("5. Vierter Kanal im VectorStore")
v = object.__new__(vsm.VectorStore)
v._lock = threading.Lock()
pfade = [str(wg.PROJECT_ROOT / p) for p in (S, D1, D2, D3)]
v._meta = [{"file_path": p, "chunk_index": i, "text": f"{Path(p).stem}-{i}", "mtime": 1}
           for p in pfade for i in range(3)]
v._gen = 1


def vektor(query, k, allowed=None):
    ids = sorted(allowed) if allowed is not None else list(range(len(v._meta)))
    return [(i, 0.9 - 0.01 * n) for n, i in enumerate(ids[:k])]


v._search_vector_idx = vektor
aufrufe = []


def rangliste(start, erlaubt, frage):
    aufrufe.append((list(start), erlaubt, frage))
    return [(pfade[3], 1.0), (pfade[2], 0.5), ("/fremd/x.md", 0.4)]


kanaele = [[(0, 0.9), (1, 0.8)], [(3, 0.7)]]          # S vor D1
erg = v._graph_kanal("frage", kanaele, rangliste, None, None, 40)
check("Positivkontrolle: Kanal liefert Chunks", len(erg) > 0, erg)
check("Startdokumente aus der vorlaeufigen Fusion (S zuerst)", aufrufe and aufrufe[0][0][:2] == pfade[:2],
      aufrufe and aufrufe[0][0])
check("die Frage geht an das Modell", aufrufe and aufrufe[0][2] == "frage", aufrufe and aufrufe[0][2])
dok = [v._meta[i]["file_path"] for i, _s in erg]
check("Reihenfolge nach Graph-Rang (D3 vor D2)", dok and dok[0] == pfade[3] and pfade[2] in dok, dok)
check("hoechstens zwei Chunks je Dokument", all(dok.count(p) <= vsm.GRAPH_CHUNKS_JE_DOKUMENT for p in set(dok)))
check("ein Dokument ausserhalb des Bestands bleibt draussen", "/fremd/x.md" not in dok)
erg2 = v._graph_kanal("frage", kanaele, rangliste, {pfade[0], pfade[2]}, None, 40)
dok2 = {v._meta[i]["file_path"] for i, _s in erg2}
check("Erlaubnis gilt auch im Kanal (D3 nicht erlaubt)", dok2 == {pfade[2]}, dok2)


def kaputt(start, erlaubt, frage):
    raise RuntimeError("Graph defekt")


try:
    _k = v._graph_kanal("frage", kanaele, kaputt, None, None, 40)
    _gut = _k == []
except Exception as _e:  # noqa: BLE001 – ein Absturz ist ein FAIL, kein Abbruch
    _gut, _k = False, repr(_e)
check("ein Fehler des Graphen ergibt keinen Kanal, keine Ausnahme", _gut, _k)

# Ganzer Durchgang: ohne Rangliste unveraendert, mit Rangliste kommt D3 hinzu.
v._search_lexical_idx = lambda q, k, allowed=None: [(3, 5.0)]
v._lex_postings = {"x": [(0, 1)]}
ohne = v._search_hybrid_once("frage", 8, None, strict=True)
ohne2 = v._search_hybrid_once("frage", 8, None, strict=True, graph_rangliste=None)
check("ohne Schalter: Durchgang identisch", ohne == ohne2)
mit = v._search_hybrid_once("frage", 8, None, strict=True, graph_rangliste=lambda s, e, f: [(pfade[3], 1.0)])
check("mit Graph: Ergebnis enthaelt Chunks des verwandten Dokuments",
      any(fp == pfade[3] for _s, fp, _t in (mit[0] if mit else [])), mit and [fp for _s, fp, _t in mit[0]])
# Kanalgewicht: nur ein lexikalischer Treffer (Chunk 0) und der Graph-Kanal.
# Platz 1 im Graph-Kanal zaehlt 0,5/(K+1), Platz 1 lexikalisch 1/(K+1) – der
# normierte Score des Graph-Chunks ist also 0,5 (Sollwert aus der Messung).
v._search_vector_idx = lambda q, k, allowed=None: [] if allowed is None else [(i, 0.9) for i in sorted(allowed)[:k]]
v._search_lexical_idx = lambda q, k, allowed=None: [(0, 5.0)]
gew = v._search_hybrid_once("frage", 8, None, strict=True, graph_rangliste=lambda s, e, f: [(pfade[3], 1.0)])
sc: dict = {}
for x, fp, _t in (gew[0] if gew else []):
    sc[fp] = max(sc.get(fp, 0.0), x)          # bester Chunk je Dokument
check("Positivkontrolle: lexikalischer Treffer oben", sc.get(pfade[0]) == 1.0, sc)
check("Graph-Kanal zaehlt halb (normierter Score 0,5)", pfade[3] in sc and abs(sc[pfade[3]] - 0.5) < 1e-9, sc)

section("6. Schalter")
check("Vorgabe: expansion AUS", wgx.VORGABEN.get("expansion") is False)
wgx._einst_cache = None
check("aus: kein Kanal", kn._graph_rangliste() is None)
check("aus: kein Block", kn._graph_zusammenhaenge([S], None) == [])
_cfgmod.config.s[wgx.EINSTELLUNG] = {"aktiv": True, "expansion": True}
wgx._einst_cache = None
fn = kn._graph_rangliste()
_r = fn([S], None, "Kostenstelle") if callable(fn) else []
check("an: Kanal liefert absolute Pfade", bool(_r) and _r[0][0].startswith("/"), _r[:1])
check("an: Block liefert Zeilen", len(kn._graph_zusammenhaenge([S, D2], None)) > 0)
_cfgmod.config.s[wgx.EINSTELLUNG] = {"aktiv": False, "expansion": True}
wgx._einst_cache = None
check("Graph aus, Schalter an: trotzdem kein Kanal", kn._graph_rangliste() is None)

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
