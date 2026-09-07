#!/usr/bin/env python3
"""Waechter: ein Reindex, der nur ETWAS ERGAENZT, darf den Index nicht leeren.

Anlass (2026-09-07, gemeldet): "warum wird der Vector-DB Index neu aufgebaut,
wenn ich eine SMB-Freigabe hinzufuege oder reaktiviere?" - zu Recht gefragt.
Beim Verbinden wird der Einhaengepunkt ueber `_kb_ordner_sicherstellen` in
`folders` aufgenommen (richtig, Fix 2026-09-04), und danach lief
`force_reindex()` OHNE `incremental`. Im FAISS-Zweig heisst das `vs.clear()`,
sobald alle Ordner erreichbar sind: die GANZE Wissensdatenbank wurde neu
eingebettet (auf ECHT ~13 Minuten fuer 12.387 Chunks), und waehrend des Laufs
war der Index leer - jede Wissenssuche meldete "keine Treffer".

Dieselbe Lehre steht im Projekt an DREI Stellen bereits (Datei loeschen,
`web_extractor._index_single_file`, `knowledge_sync`); die Mount-Stellen waren
die vergessenen.

Geprueft wird die EIGENSCHAFT, nicht der Wortlaut:
  1. REGEL ueber den AST: in `backend/main.py` darf ein `force_reindex`-Aufruf
     ohne `incremental=True` nur im ausdruecklichen Neuaufbau-Endpunkt stehen.
     Damit faellt auch eine KUENFTIGE Aufrufstelle auf, ohne dass jemand eine
     Liste pflegt.
  2. `_do_force_reindex` wird WIRKLICH AUSGEFUEHRT (per ast geschnitten, gegen
     Attrappen): mit `incremental=True` darf kein `vs.clear()` laufen, ohne
     das Flag muss es laufen. Eine Quelltext-Suche bliebe gruen, sobald jemand
     den Zweig spaeter ueberspringt.
  3. Das Aufraeumen verwaister Eintraege laeuft in BEIDEN Faellen
     (`_rebuild_vector_index(..., force=True)`) - sonst waere der inkrementelle
     Weg ein Datenleck in die andere Richtung: geloeschte Dateien blieben ewig
     im Index.
  4. Der Startzeitpunkt wird nur bei einer WIEDERAUFNAHME (`resume_count > 0`)
     vom vorherigen Lauf uebernommen, nicht bei jedem inkrementellen Lauf -
     sonst zeigt "Letzter Indexlauf" den Zeitpunkt eines FREMDEN Laufs.
"""
import ast
import builtins
import pathlib
import sys
import time

WURZEL = pathlib.Path(__file__).resolve().parent.parent
MAIN = WURZEL / "backend" / "main.py"
KNOW = WURZEL / "backend" / "tools" / "knowledge.py"

# Der einzige Ort, an dem ein VOLLER Neuaufbau richtig ist: der Knopf
# "Neu indizieren". Genau dafuer gibt es ihn.
VOLL_ERLAUBT = {"reindex_knowledge"}

_ok = 0
_fail = 0


def pruefe(beschreibung: str, bedingung) -> bool:
    """Reihenfolge ist (Text, Bedingung) - vertauschte Argumente brechen ab.

    Eine nicht-leere Zeichenkette ist wahr; ein vertauschter Aufruf meldete
    sonst OK, ohne je eine Bedingung ausgewertet zu haben (im Projekt bezahlt).
    """
    global _ok, _fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: pruefe(text, bedingung) - Argumente vertauscht", flush=True)
        sys.exit(2)
    try:
        wahr = bool(bedingung)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {beschreibung}  [Bedingung wirft: {e}]", flush=True)
        _fail += 1
        return False
    if wahr:
        _ok += 1
        print(f"OK   {beschreibung}", flush=True)
    else:
        _fail += 1
        print(f"FAIL {beschreibung}", flush=True)
    return wahr


# ─────────────────────────────────────────────────────────────────────────────
# Teil 1: REGEL - kein Voll-Neuaufbau ausserhalb des Neuaufbau-Endpunkts
# ─────────────────────────────────────────────────────────────────────────────
print("\n== Teil 1: Regel ueber alle force_reindex-Aufrufe in main.py ==")

baum = ast.parse(MAIN.read_text(encoding="utf-8"), str(MAIN))

# Jeden Knoten seiner AEUSSERSTEN Funktion zuordnen. Der Mount-Aufruf steckt in
# einer inneren Hintergrund-Funktion; aussagekraeftig ist der Endpunkt darum.
besitzer: dict[int, str] = {}


def _zuordnen(knoten, name: str | None):
    for kind in ast.iter_child_nodes(knoten):
        if isinstance(kind, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _zuordnen(kind, name or kind.name)
        else:
            besitzer[id(kind)] = name or "<modul>"
            _zuordnen(kind, name)


for oben in baum.body:
    if isinstance(oben, (ast.FunctionDef, ast.AsyncFunctionDef)):
        besitzer[id(oben)] = oben.name
        _zuordnen(oben, oben.name)
    else:
        besitzer[id(oben)] = "<modul>"
        _zuordnen(oben, None)


def _ist_force_reindex(knoten) -> bool:
    """Trifft `force_reindex(...)` UND `to_thread(force_reindex, ...)`."""
    if not isinstance(knoten, ast.Call):
        return False
    f = knoten.func
    if isinstance(f, ast.Name) and f.id == "force_reindex":
        return True
    if isinstance(f, ast.Attribute) and f.attr == "to_thread":
        for a in knoten.args:
            if isinstance(a, ast.Name) and a.id == "force_reindex":
                return True
    return False


def _hat_incremental_true(knoten: ast.Call) -> bool:
    for kw in knoten.keywords:
        if kw.arg == "incremental":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    # Positional: force_reindex(resume_count, incremental, ...) bzw.
    # to_thread(force_reindex, resume_count, incremental, ...)
    args = list(knoten.args)
    if isinstance(knoten.func, ast.Attribute) and knoten.func.attr == "to_thread":
        args = args[1:]
    if len(args) >= 2:
        return isinstance(args[1], ast.Constant) and args[1].value is True
    return False


aufrufe = [k for k in ast.walk(baum) if _ist_force_reindex(k)]
pruefe(f"force_reindex-Aufrufe in main.py gefunden ({len(aufrufe)})", len(aufrufe) >= 4)

verstoesse = []
for k in aufrufe:
    fn = besitzer.get(id(k), "<unbekannt>")
    if not _hat_incremental_true(k) and fn not in VOLL_ERLAUBT:
        verstoesse.append(f"{fn} (Zeile {k.lineno})")

pruefe("kein Voll-Neuaufbau ausserhalb des Neuaufbau-Endpunkts: "
       + (", ".join(verstoesse) if verstoesse else "keiner"),
       not verstoesse)

# Positivkontrolle: der ausdrueckliche Neuaufbau MUSS voll bleiben - sonst
# koennte der Benutzer einen kaputten Index nie mehr sauber neu aufbauen.
voll_im_endpunkt = [k for k in aufrufe
                    if besitzer.get(id(k)) == "reindex_knowledge"
                    and not _hat_incremental_true(k)]
pruefe("der Knopf 'Neu indizieren' baut weiterhin VOLL auf",
       len(voll_im_endpunkt) == 1)

# Die drei ergaenzenden Stellen namentlich - sie sind der gemeldete Fall.
inkrementell = {besitzer.get(id(k)) for k in aufrufe if _hat_incremental_true(k)}
for name in ("mount_share", "startup", "knowledge_extract_confluence"):
    pruefe(f"'{name}' ergaenzt inkrementell", name in inkrementell)


# ─────────────────────────────────────────────────────────────────────────────
# Teil 2-4: _do_force_reindex WIRKLICH AUSFUEHREN
# ─────────────────────────────────────────────────────────────────────────────
print("\n== Teil 2: _do_force_reindex ausgefuehrt (Attrappen) ==")

quelle = KNOW.read_text(encoding="utf-8")
kbaum = ast.parse(quelle, str(KNOW))
schnitt = None
for k in kbaum.body:
    if isinstance(k, ast.FunctionDef) and k.name == "_do_force_reindex":
        schnitt = ast.get_source_segment(quelle, k)
if schnitt is None:
    print("ABBRUCH: _do_force_reindex nicht gefunden (umbenannt?)", flush=True)
    sys.exit(2)


class Attrappe:
    """Alles, was aufgerufen/attributiert wird, ohne dass es hier zaehlt."""

    def __init__(self, name="?"):
        self._name = name

    def __call__(self, *a, **kw):
        return Attrappe(self._name)

    def __getattr__(self, item):
        return Attrappe(f"{self._name}.{item}")

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __int__(self):
        return 0


class Namensraum(dict):
    """Toleranter Namensraum.

    ⚠ ZUERST in `builtins` sehen: bei einem dict-Nachfahren als `globals` ruft
    CPython `__missing__` und erreicht die Builtins danach NICHT mehr - aus
    `str(e)` wuerde sonst `None(e)`, und ein Fehler im geschnittenen Code waere
    unauffindbar (im Projekt bezahlt).
    """

    def __missing__(self, key):
        if hasattr(builtins, key):
            return getattr(builtins, key)
        return Attrappe(key)


def lauf(incremental: bool, resume_count: int = 0, alle_erreichbar: bool = True,
         letzter_start: float = 0.0) -> dict:
    """Fuehrt den echten Funktionsrumpf aus und protokolliert, was er tut."""
    spur: list[str] = []
    ordner = ["/mnt/kb/share_1", "/data/knowledge"]

    class VS:
        def clear(self):
            spur.append("clear")

        def get_indexed_files(self):
            return {"/data/knowledge/a.md": 1.0}

        def remove_files(self, pfade):
            spur.append(f"remove_files:{len(pfade)}")
            return len(pfade)

        def chunk_count(self):
            return 42

        def file_count(self):
            return 7

    gespeichert: dict = {}

    def _rebuild(folders, max_bytes, force=False):
        spur.append(f"rebuild(force={force})")
        return True

    ns = Namensraum({
        "time": time,
        "_log": Attrappe("_log"),
        "get_last_run": lambda: ({"started_at": letzter_start} if letzter_start else {}),
        "_set_progress": lambda **kw: spur.append("set_progress"),
        "_save_last_run": lambda run: gespeichert.update(run),
        "_get_folders": lambda: ordner,
        "_get_max_bytes": lambda: 10_000_000,
        "_get_vector_store": lambda: VS(),
        "invalidate_files_cache": lambda: spur.append("cache_invalidate"),
        "_nutzbare_ordner": lambda folders, indexed, streng=False: (
            list(folders) if alle_erreichbar else list(folders)[1:]),
        "_rebuild_vector_index": _rebuild,
        "get_index_progress": lambda: {"failed": 0, "failed_list": []},
        "known_paths_with_disk": lambda: set(),
        "_reindex_cancel": Attrappe("_reindex_cancel"),
        "MAX_INDEX_ATTEMPTS": 3,
        "os": __import__("os"),
    })
    exec(compile(schnitt, "<_do_force_reindex>", "exec"), ns)
    ergebnis = ns["_do_force_reindex"](attempt=1, resume_count=resume_count,
                                       incremental=incremental, resume_baseline=-1)
    return {"spur": spur, "gespeichert": gespeichert, "ergebnis": ergebnis}


try:
    voll = lauf(incremental=False)
    inkr = lauf(incremental=True)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Lauf wirft: {type(e).__name__}: {e}", flush=True)
    sys.exit(2)

pruefe("Voll-Neuaufbau leert den Index (Positivkontrolle des Messaufbaus)",
       "clear" in voll["spur"])
pruefe("inkrementell leert den Index NICHT - der gemeldete Fall",
       "clear" not in inkr["spur"])
pruefe("inkrementell baut trotzdem auf (rebuild laeuft)",
       any(s.startswith("rebuild(") for s in inkr["spur"]))

print("\n== Teil 3: Aufraeumen laeuft in BEIDEN Faellen ==")
pruefe("Voll-Lauf raeumt verwaiste Eintraege auf (force=True)",
       "rebuild(force=True)" in voll["spur"])
pruefe("inkrementeller Lauf raeumt ebenfalls auf (force=True)",
       "rebuild(force=True)" in inkr["spur"])

print("\n== Teil 4: Startzeitpunkt haengt an der WIEDERAUFNAHME ==")
ALT = 1_000_000.0
w = lauf(incremental=True, resume_count=2, letzter_start=ALT)
pruefe("Wiederaufnahme uebernimmt den urspruenglichen Start",
       w["gespeichert"].get("started_at") == ALT)

i = lauf(incremental=True, resume_count=0, letzter_start=ALT)
pruefe("inkrementeller Lauf OHNE Wiederaufnahme startet mit JETZT, nicht mit "
       "dem Zeitpunkt eines fremden Laufs",
       i["gespeichert"].get("started_at", 0) > ALT)

v = lauf(incremental=False, resume_count=0, letzter_start=ALT)
pruefe("Voll-Lauf ebenso", v["gespeichert"].get("started_at", 0) > ALT)

print("\n== Teil 5: Teil-Neuaufbau bleibt erhalten ==")
teil = lauf(incremental=False, alle_erreichbar=False)
pruefe("bei nur teilweise erreichbaren Ordnern wird NICHT geleert",
       "clear" not in teil["spur"])
pruefe("stattdessen werden die Eintraege der erreichbaren Ordner entfernt",
       any(s.startswith("remove_files:") for s in teil["spur"]))

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
