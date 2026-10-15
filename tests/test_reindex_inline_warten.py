#!/usr/bin/env python3
"""Waechter: Neuaufbau und Inline-Lauf ueberlappen sich nie (Review 2026-09-28 #10).

⚠ DER BEFUND: ``_inline_vector_index`` prueft ``_reindex_lock`` nur mit
``locked()``, haelt ihn aber nicht - und ``force_reindex`` nahm
``_inline_index_lock`` nie. Begann ein Inline-Lauf (Suchpfad) kurz VOR dem
Neuaufbau, liefen beide ueber dieselben Dateien: doppelte OCR/Einbettung,
Fortschritt > 100 %.

ZUSAGEN:
  1. Laeuft ein Inline-Lauf, beginnt der Neuaufbau erst NACH dessen Ende.
  2. Der Neuaufbau wird dabei NICHT uebersprungen (ein verlorener Klick).
  3. Nach dem Neuaufbau sind BEIDE Sperren frei - auch nach einer Ausnahme.

AUSGEFUEHRT, nicht am Text: ``force_reindex`` laeuft echt, gestubbt ist nur
``_run_with_retries`` (der Lauf selbst).
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


def _wachhund():
    # Eine Sabotage (z.B. Sperre nie freigegeben) haengt den Lauf - dann mit
    # Bilanz abbrechen statt ewig zu warten.
    time.sleep(30)
    print(f"\nERGEBNIS: {_ok} OK, {_fail + 1} FAIL  (ABBRUCH: Wachhund nach 30s)",
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


QUELL = KNOW.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
FN = {n.name: n for n in BAUM.body if isinstance(n, ast.FunctionDef)}

print("\n=== 1. Namens-Guard ===")
for noetig in ("force_reindex", "_run_with_retries"):
    check(f"{noetig} existiert", noetig in FN, "Altstand?")
if "force_reindex" not in FN:
    print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL  (ABBRUCH: konnte nicht laufen)")
    sys.exit(2)
SCHNITT = ast.get_source_segment(QUELL, FN["force_reindex"])


def baue(lauf_dauer=0.3, wirft=False):
    zeit = {"lauf_start": None, "lauf_ende": None, "laeufe": 0}

    def run_stub(resume_count=0, incremental=False, resume_baseline=-1):
        zeit["laeufe"] += 1
        zeit["lauf_start"] = time.monotonic()
        time.sleep(lauf_dauer)
        zeit["lauf_ende"] = time.monotonic()
        if wirft:
            raise RuntimeError("Lauf scheitert")
        return {"ok": True}

    ns = {
        "threading": threading, "time": time,
        "_log": type("L", (), {"info": staticmethod(lambda *a, **k: None)})(),
        "_reindex_lock": threading.Lock(),
        "_inline_index_lock": threading.Lock(),
        "_reindex_rerun": threading.Event(),
        "_reindex_cancel": threading.Event(),
        "_run_with_retries": run_stub,
    }
    exec(SCHNITT, ns)  # noqa: S102
    return ns, zeit


print("\n=== 2. Inline-Lauf laeuft -> Neuaufbau wartet ===")
ns, zeit = baue(lauf_dauer=0.1)
inline = {"ende": None}


def inline_lauf():
    # Nachgebildet wie im Suchpfad: Sperre nehmen, arbeiten, freigeben.
    with ns["_inline_index_lock"]:
        time.sleep(0.4)
        inline["ende"] = time.monotonic()


t_inline = threading.Thread(target=inline_lauf, daemon=True)
t_inline.start()
time.sleep(0.05)                      # Inline-Lauf sitzt sicher im Lauf
check("Positivkontrolle: Inline-Sperre ist besetzt", ns["_inline_index_lock"].locked())
erg = ns["force_reindex"]()
t_inline.join(5)
check("Neuaufbau wurde NICHT uebersprungen", erg == {"ok": True}, repr(erg))
check("der Lauf lief genau einmal", zeit["laeufe"] == 1, str(zeit["laeufe"]))
check("⚠ Neuaufbau begann erst NACH dem Inline-Lauf",
      zeit["lauf_start"] is not None and inline["ende"] is not None
      and zeit["lauf_start"] >= inline["ende"],
      f"start={zeit['lauf_start']} inline_ende={inline['ende']} - Ueberlappung")
check("danach _reindex_lock frei", not ns["_reindex_lock"].locked())
check("danach _inline_index_lock frei", not ns["_inline_index_lock"].locked())

print("\n=== 3. Waehrend des Neuaufbaus ist die Inline-Sperre besetzt ===")
ns2, _z2 = baue(lauf_dauer=0.4)
t = threading.Thread(target=ns2["force_reindex"], daemon=True)
t.start()
time.sleep(0.1)
check("Suchpfad bekommt die Inline-Sperre nicht (ueberspringt)",
      not ns2["_inline_index_lock"].acquire(blocking=False))
t.join(5)
check("nach dem Lauf beide Sperren frei",
      not ns2["_reindex_lock"].locked() and not ns2["_inline_index_lock"].locked())

print("\n=== 4. Ausnahme im Lauf -> beide Sperren frei ===")
ns3, _z3 = baue(lauf_dauer=0.01, wirft=True)
try:
    ns3["force_reindex"]()
    geworfen = False
except RuntimeError:
    geworfen = True
check("Positivkontrolle: der Lauf hat geworfen", geworfen)
check("_reindex_lock frei nach Ausnahme", not ns3["_reindex_lock"].locked())
check("_inline_index_lock frei nach Ausnahme", not ns3["_inline_index_lock"].locked(),
      "sonst laeuft im Suchpfad NIE wieder ein Inline-Lauf")

print("\n=== 5. Zweiter Neuaufbau waehrend des ersten: Rerun statt Warten ===")
ns4, _z4 = baue(lauf_dauer=0.3)
t = threading.Thread(target=ns4["force_reindex"], daemon=True)
t.start()
time.sleep(0.05)
t0 = time.monotonic()
r = ns4["force_reindex"]()
check("zweiter Aufruf kehrt sofort zurueck", time.monotonic() - t0 < 0.1,
      f"{time.monotonic() - t0:.2f}s")
check("zweiter Aufruf meldet skipped", isinstance(r, dict) and r.get("skipped"), repr(r))
t.join(5)

print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
