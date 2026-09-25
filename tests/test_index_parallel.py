#!/usr/bin/env python3
"""Waechter: im Suchpfad laeuft hoechstens EIN Indexlauf gleichzeitig.

⚠ DER BEFUND (2026-09-24): ``_rebuild_vector_index`` lief im Suchpfad OHNE jede
Sperre - ``_reindex_lock`` nimmt ausschliesslich ``force_reindex``. N gleichzeitige
``knowledge_search`` starteten damit N Indexlaeufe in eigenen Threads
(``asyncio.to_thread``), und zwar ueber DIESELBEN Dateien: die mtime wird erst
NACH Erfolg geschrieben, keiner sieht den anderen. Bei einem Bestand aus 90 % PDF
heisst das dieselbe Seite mehrfach gleichzeitig durch die OCR - auf einem
4-Kern-Server gemessen rund 26 s je Datei.

DREI ZUSAGEN, und jede hat ihren eigenen Grund:
  1. Nur EINER arbeitet gleichzeitig.
  2. Wer die Sperre nicht bekommt, WARTET NICHT, sondern ueberspringt. Eine
     blockierende Sperre haengt die Suche an einen Lauf, der Minuten dauern kann -
     der Benutzer bekaeme gar keine Antwort statt einer aus einem Index, der ein
     paar Sekunden alt ist.
  3. Der uebersprungene Lauf gibt DIESELBE Antwort. ``False`` heisst fuer den
     Aufrufer "kein Vektor-Index" und schickt ihn in den TF-IDF-Rueckfall bzw. in
     "bitte neu indizieren" - fuer einen uebersprungenen Lauf waere das eine
     Falschaussage ueber einen vollstaendig nutzbaren Index.

GEMESSEN WIRD AUSGEFUEHRT: ob zwei Threads wirklich nur einmal in den Lauf
kommen, kann eine Quelltext-Pruefung nicht beantworten. Gestubbt ist nur
``_vector_index_lauf`` (der Lauf selbst ist unveraendert) - die WEICHE davor ist
das Neue und laeuft echt.
"""
import ast
import os
import sys
import threading
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
KNOW = WURZEL / "backend" / "tools" / "knowledge.py"

_ok = 0
_fail = 0

# ⚠ WACHHUND. Eine Sabotage kann diesen Waechter zum HAENGEN bringen – etwa
# "blockierende Sperre statt ueberspringen": die Abschnitte 4 und 6 nehmen die
# Sperre selbst und rufen dann auf, das wartet dann ewig. Ein haengender
# Waechter ist von "nicht gelaufen" nicht zu unterscheiden, und die Gegenprobe
# kann nicht beurteilen, ob sie gebissen hat. Also: mit Bilanz abbrechen.
def _wachhund():
    time.sleep(60)
    print(f"\nERGEBNIS: {_ok} OK, {_fail + 1} FAIL  "
          f"(ABBRUCH: Wachhund nach 60s – haengt der Lauf an einer Sperre?)",
          flush=True)
    os._exit(1)


threading.Thread(target=_wachhund, daemon=True).start()


def check(text, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{detail}]" if detail else ""))


def sicher(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return f"<WURF {type(e).__name__}: {e}>"


QUELL = KNOW.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
NAMEN = {n.name for n in BAUM.body if isinstance(n, ast.FunctionDef)}

print("\n=== 1. Namens-Guard ===")
for noetig in ("_rebuild_vector_index", "_inline_vector_index", "_vector_index_lauf"):
    check(f"{noetig} existiert", noetig in NAMEN, "Altstand?")
if not {"_rebuild_vector_index", "_inline_vector_index"} <= NAMEN:
    print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL  (ABBRUCH: Altstand)")
    sys.exit(1)

print("\n=== 2. Der Suchpfad haelt ueberhaupt eine Sperre ===")
# Vor dem Fix nahm NUR force_reindex eine Sperre. Gemessen wird, dass die
# Suchpfad-Weiche eine EIGENE nimmt - und zwar nicht blockierend.
rvi = next(n for n in BAUM.body
           if isinstance(n, ast.FunctionDef) and n.name == "_rebuild_vector_index")
rvi_src = ast.get_source_segment(QUELL, rvi) or ""
check("_rebuild_vector_index nimmt _inline_index_lock", "_inline_index_lock" in rvi_src)
check("und zwar NICHT blockierend (acquire(blocking=False))",
      "acquire(blocking=False)" in rvi_src,
      "eine blockierende Sperre haengt die Suche an einen Lauf von Minuten")
check("_inline_index_lock ist auf Modulebene definiert",
      any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_inline_index_lock"
                                            for t in n.targets) for n in BAUM.body))
# REGEL: die Freigabe muss in einem finally stehen - sonst bleibt die Sperre
# nach der ersten Ausnahme fuer immer zu, und es laeuft NIE wieder ein Lauf.
freigabe_im_finally = False
for k in ast.walk(rvi):
    if isinstance(k, ast.Try) and k.finalbody:
        if "_inline_index_lock.release()" in (ast.get_source_segment(QUELL, k) or ""):
            freigabe_im_finally = True
check("die Freigabe steht in einem finally", freigabe_im_finally,
      "ohne finally bleibt die Sperre nach der ersten Ausnahme dauerhaft zu")

print("\n=== 3. AUSGEFUEHRT: zwei gleichzeitige Suchen, ein Lauf ===")
# Geschnitten werden NUR die beiden Weichen. Der Lauf selbst ist Bestand und
# wird gestubbt - so misst der Waechter genau das Neue.
schnitt = {n.name: ast.get_source_segment(QUELL, n) for n in BAUM.body
           if isinstance(n, ast.FunctionDef)
           and n.name in ("_rebuild_vector_index", "_inline_vector_index")}
check("Schnitt vollstaendig (beide Weichen)", len(schnitt) == 2, str(list(schnitt)))


class _VS:
    """Vektor-Store-Attrappe: der Index ist GEFUELLT (chunk_count > 0)."""

    def __init__(self, chunks=4711):
        self._c = chunks

    def get_indexed_files(self):
        return {"/rag/a.pdf": 1.0}

    def chunk_count(self):
        return self._c


def baue(lauf_dauer=0.30, reindex_laeuft=False, chunks=4711):
    """Namensraum mit den ECHTEN Weichen und gestubbtem Lauf."""
    zaehler = {"laeufe": 0, "gleichzeitig": 0, "max_gleichzeitig": 0}
    sperre = threading.Lock()

    def lauf_stub(vs, indexed, folders, max_bytes, force):
        with sperre:
            zaehler["laeufe"] += 1
            zaehler["gleichzeitig"] += 1
            zaehler["max_gleichzeitig"] = max(zaehler["max_gleichzeitig"],
                                              zaehler["gleichzeitig"])
        time.sleep(lauf_dauer)          # ein echter Lauf dauert - sonst gibt es
        with sperre:                    # gar keine Gleichzeitigkeit zu messen
            zaehler["gleichzeitig"] -= 1
        return True

    reindex = threading.Lock()
    if reindex_laeuft:
        reindex.acquire()

    ns = {
        "threading": threading, "time": time, "Path": Path,
        "_log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                               "info": staticmethod(lambda *a, **k: None),
                               "warning": staticmethod(lambda *a, **k: None)})(),
        "_get_vector_store": lambda: _VS(chunks),
        "_vector_index_lauf": lauf_stub,
        "_inline_index_lock": threading.Lock(),
        "_reindex_lock": reindex,
    }
    exec("\n".join(schnitt.values()), ns)  # noqa: S102
    return ns, zaehler


def parallel(ns, n=4):
    """n gleichzeitige Suchpfad-Aufrufe, Rueckgaben und Wanduhr."""
    aus = []
    sperre = threading.Lock()

    def einer():
        r = ns["_rebuild_vector_index"]([Path("/rag")], 1000, False)
        with sperre:
            aus.append(r)

    faeden = [threading.Thread(target=einer, daemon=True) for _ in range(n)]
    t0 = time.monotonic()
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(timeout=30)
    return aus, time.monotonic() - t0


# ⚠ POSITIVKONTROLLE DES MESSAUFBAUS, und sie ist nicht optional: ohne Sperre
# MUESSEN mehrere Threads gleichzeitig im Lauf sein. Sind die Laeufe zu kurz,
# um sich zu ueberlappen, waere "nur EIN Lauf" weiter unten trivial wahr - der
# Waechter meldete dann gruen, ohne jemals Gleichzeitigkeit gesehen zu haben.
_ns0, _z0 = baue(lauf_dauer=0.30)
_ns0["_inline_index_lock"] = type("Frei", (), {          # Sperre, die nie sperrt
    "acquire": staticmethod(lambda blocking=True: True),
    "release": staticmethod(lambda: None)})()
parallel(_ns0, 4)
check("Positivkontrolle: OHNE Sperre laufen mehrere gleichzeitig",
      _z0["max_gleichzeitig"] >= 2,
      f"max {_z0['max_gleichzeitig']} - der Aufbau stellt die Lage nicht her, "
      f"jede Aussage darunter waere trivial")

ns, z = baue(lauf_dauer=0.30)
ergebnisse, dauer = parallel(ns, 4)
check("nur EIN Lauf trotz 4 gleichzeitiger Suchen", z["laeufe"] == 1,
      f"{z['laeufe']} Laeufe")
check("nie zwei gleichzeitig im Lauf", z["max_gleichzeitig"] <= 1,
      f"max {z['max_gleichzeitig']}")

# ⚠ DIE WICHTIGSTE: die uebersprungenen duerfen nicht WARTEN.
# 4 Threads, Lauf dauert 0,30 s. Gesamtdauer nahe 0,30 s = uebersprungen;
# nahe 1,20 s = sie haben sich angestellt (blockierende Sperre).
check("die uebrigen WARTEN nicht (Gesamtdauer ~ ein Lauf)", dauer < 0.30 * 2.2,
      f"{dauer:.2f}s bei 4 Threads a 0,30s Lauf - >0,66s hiesse angestellt")

check("alle 4 bekommen eine Antwort", len(ergebnisse) == 4, str(len(ergebnisse)))
check("⚠ die uebersprungenen melden True (Index ist ja gefuellt), nicht False",
      all(r is True for r in ergebnisse), str(ergebnisse))

print("\n=== 4. Leerer Index: uebersprungen heisst NICHT faelschlich True ===")
ns2, _z2 = baue(lauf_dauer=0.05, chunks=0)
# chunk_count()==0 -> auch der uebersprungene Lauf muss False melden.
# (get_indexed_files ist nicht leer, also greift die fruehe Rueckgabe nicht.)
ns2["_inline_index_lock"].acquire()          # Sperre besetzt = jeder ueberspringt
r = sicher(ns2["_rebuild_vector_index"], [Path("/rag")], 1000, False)
ns2["_inline_index_lock"].release()
check("uebersprungen + leerer Index -> False", r is False, repr(r))

print("\n=== 5. Laufender Voll-Reindex: kein Inline-Lauf daneben ===")
ns3, z3 = baue(lauf_dauer=0.05, reindex_laeuft=True)
r3 = sicher(ns3["_rebuild_vector_index"], [Path("/rag")], 1000, False)
check("waehrend force_reindex laeuft KEIN Inline-Lauf", z3["laeufe"] == 0,
      f"{z3['laeufe']} Laeufe - das waere Doppelarbeit an denselben Dateien")
check("und die Antwort bleibt richtig (Index gefuellt -> True)", r3 is True, repr(r3))

ns4, z4 = baue(lauf_dauer=0.05, reindex_laeuft=False)
r4 = sicher(ns4["_rebuild_vector_index"], [Path("/rag")], 1000, False)
check("Positivkontrolle: ohne laufenden Reindex arbeitet er", z4["laeufe"] == 1,
      f"{z4['laeufe']}")

print("\n=== 6. force=True ist UNBERUEHRT (der Neuaufbau hat seine eigene Sperre) ===")
ns5, z5 = baue(lauf_dauer=0.05)
ns5["_inline_index_lock"].acquire()          # Suchpfad waere blockiert...
r5 = sicher(ns5["_rebuild_vector_index"], [Path("/rag")], 1000, True)
ns5["_inline_index_lock"].release()
check("force=True laeuft trotz besetzter Inline-Sperre", z5["laeufe"] == 1,
      f"{z5['laeufe']} - force_reindex haelt bereits _reindex_lock")
check("force=True liefert das Lauf-Ergebnis", r5 is True, repr(r5))

# Und force=True darf die Inline-Sperre gar nicht erst anfassen - sonst
# blockierten sich Neuaufbau und Suche gegenseitig aus.
# ⚠ .find() statt .index(): letzteres WIRFT, wenn der Text fehlt (etwa weil eine
# Gegenprobe die Sperre ganz entfernt hat) - der Lauf endete dann OHNE
# Bilanzzeile und die Probe waere nicht beurteilbar.
_i_sperre = rvi_src.find("_inline_index_lock")
_i_force = rvi_src.find("if not force:")
check("die Sperre liegt im NICHT-force-Zweig",
      _i_sperre > 0 and _i_force > 0 and _i_sperre > _i_force,
      f"Sperre@{_i_sperre} force@{_i_force} - sonst nimmt auch der Neuaufbau sie")

print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
