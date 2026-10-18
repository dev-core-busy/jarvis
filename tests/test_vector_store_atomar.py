#!/usr/bin/env python3
"""Waechter: der FAISS-Index wird atomar gespeichert, und ein unlesbarer Index
geht nicht still verloren (Code-Review 2026-10-18).

AUSGEFUEHRT am echten ``VectorStore`` in einem Wegwerf-Verzeichnis, mit
Zufallsvektoren (kein Modell noetig):
  [1] speichern + neu laden ergibt denselben Bestand; keine Temp-Datei bleibt
  [2] schlaegt das Ersetzen fehl, bleiben die vorigen Dateien unversehrt
  [3] ein kaputter Index wird BEISEITE gelegt (``*.defekt-*``), nicht
      ueberschrieben – der Bestand ist danach noch auf der Platte
Braucht numpy + faiss (auf dem Server vorhanden); fehlen sie: Exit 2.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


try:
    import numpy as np
    import faiss  # noqa: F401
    from backend.tools import vector_store as V
except Exception as e:  # noqa: BLE001
    print("ABBRUCH (Exit 2): numpy/faiss/vector_store nicht verfuegbar: %s" % e)
    sys.exit(2)

SK = Path(tempfile.mkdtemp(prefix="vs_atomar_"))


def fuellen(vs, n):
    rng = np.random.default_rng(7)
    vec = rng.standard_normal((n, V.EMBEDDING_DIM)).astype("float32")
    vec /= np.linalg.norm(vec, axis=1, keepdims=True)
    vs._index.add(vec)
    vs._meta.extend({"file_path": f"data/rag/a/{i}.md", "mtime": 1.0, "chunk_index": 0, "text": f"t{i}"}
                    for i in range(n))


try:
    print("\n[1] speichern und laden")
    vs = V.VectorStore(SK)
    fuellen(vs, 5)
    vs.save()
    vs2 = V.VectorStore(SK)
    check("(Positivkontrolle) neu geladen: 5 Chunks", len(vs2._meta) == 5 and vs2._index.ntotal == 5,
          "%d/%d" % (len(vs2._meta), vs2._index.ntotal))
    if FAIL:
        print("ABBRUCH: Messaufbau traegt nicht")
        sys.exit(2)
    check("keine Temp-Datei bleibt liegen", not any(p.name.endswith(".tmp") for p in SK.iterdir()),
          str([p.name for p in SK.iterdir()]))

    print("\n[2] Ersetzen scheitert -> vorige Dateien unversehrt")
    vor_idx = (SK / "faiss_index.bin").read_bytes()
    vor_meta = (SK / "faiss_meta.json").read_bytes()
    fuellen(vs2, 3)
    echt = os.replace
    try:
        V.os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("Probe: Platte voll"))
        vs2.save()
    finally:
        V.os.replace = echt
    check("Index-Datei unveraendert", (SK / "faiss_index.bin").read_bytes() == vor_idx)
    check("Metadaten unveraendert", (SK / "faiss_meta.json").read_bytes() == vor_meta)
    check("keine Temp-Reste", not any(p.name.endswith(".tmp") for p in SK.iterdir()))

    print("\n[3] kaputter Index wird beiseite gelegt, nicht ueberschrieben")
    (SK / "faiss_index.bin").write_bytes(b"kaputt")
    vs3 = V.VectorStore(SK)
    defekt = [p.name for p in SK.iterdir() if ".defekt-" in p.name]
    check("unlesbare Dateien als *.defekt-* beiseite gelegt", len(defekt) == 2, str(defekt))
    check("die Metadaten des Bestands liegen noch auf der Platte",
          any(n.startswith("faiss_meta.json.defekt-") and (SK / n).read_bytes() == vor_meta for n in defekt))
    vs3.save()
    check("ein Speichern danach ueberschreibt die beiseite gelegten Dateien NICHT",
          len([p for p in SK.iterdir() if ".defekt-" in p.name]) == 2)
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
