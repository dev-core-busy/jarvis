#!/usr/bin/env python3
"""Live-Probe auf DEV: eine echte .one-Datei durch die ECHTE Indizierung.

Nicht der Extraktor wird hier geprueft (das macht der Waechter), sondern die
KETTE: erfasst _all_files die Datei, liest _extract_text sie, entstehen Chunks,
und findet die Suche den Inhalt wieder. Genau die Kette, die eine vergessene
Endungs-Stelle stillschweigend unterbrochen haette.

Raeumt hinterher vollstaendig auf – und prueft VORHER auf Rueckstaende (Lehre
vom 2026-08-30: eine Wiederherstellung gegen einen verunreinigten Ausgangsstand
beweist nichts).
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
from backend.tools import knowledge as K            # noqa: E402
from backend.tools import onenote as ON             # noqa: E402

OK = FAIL = 0


def check(text, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {text}")
    else:
        FAIL += 1
        print(f"  FAIL {text}" + (f"  -> {detail}" if detail else ""))


for _n in ("_all_files", "_extract_text", "force_reindex", "get_stats", "rag_search"):
    if not hasattr(K, _n):
        print(f"ABBRUCH: knowledge.{_n} gibt es nicht (umbenannt?)")
        sys.exit(2)

QUELLE = Path("/opt/jarvis/tests/fixtures/onenote/abschnitt_2016.one")
ORDNER = K._get_folders()
check("Wissensordner konfiguriert", bool(ORDNER), str(ORDNER))
ZIEL = ORDNER[0] / "live_onenote_probe.one"

if ZIEL.exists():
    print(f"ABBRUCH: Rueckstand einer frueheren Probe: {ZIEL}")
    sys.exit(2)

print(f"Voraussetzungen: Java={ON.finde_java()} Tika={ON.finde_tika()}")
check("Voraussetzungen vorhanden", bool(ON.finde_java() and ON.finde_tika()))
check("get_stats meldet onenote_support", K.get_stats().get("onenote_support") is True,
      repr(K.get_stats().get("onenote_support")))

vorher = K.get_stats()
print(f"vor der Probe: {vorher['indexed_files']} indiziert, {vorher['total_chunks']} Chunks")

shutil.copy2(QUELLE, ZIEL)
try:
    # 1. Sieht der Datei-Sammler sie?
    dateien = K._all_files(ORDNER)
    check("_all_files erfasst die .one-Datei", ZIEL in dateien,
          f"{len(dateien)} Dateien gesammelt")

    # 2. Liest der Extraktor sie ueber den PRODUKTIVEN Weg?
    t0 = time.time()
    text = K._extract_text(ZIEL, 50 * 1024 * 1024)
    dauer = time.time() - t0
    check("_extract_text liefert Text", isinstance(text, str) and len(text) > 20,
          repr(text)[:80])
    check("der Inhalt der Notiz ist dabei",
          isinstance(text, str) and "This is one note 2016" in text, repr(text)[:120])
    check("keine Dublette im indizierten Text",
          isinstance(text, str) and text.count("So good") == 1, repr(text))
    print(f"       ({dauer:.1f}s, {len(text or '')} Zeichen)")

    # 3. Inkrementeller Reindex und Suche - die eigentliche Zusage.
    e = K.force_reindex(incremental=True)
    print(f"       Reindex: {e}")
    nachher = K.get_stats()
    check("Reindex hat die Datei aufgenommen",
          nachher["indexed_files"] >= vorher["indexed_files"] + 1,
          f"{vorher['indexed_files']} -> {nachher['indexed_files']}")

    # rag_search ist der produktive Sucheinstieg (async).
    import asyncio
    treffer = asyncio.run(K.rag_search("This is one note 2016", max_results=8))
    pfade = [str(t[1]) for t in (treffer or [])]
    check("die Suche findet den Notizinhalt wieder",
          any("live_onenote_probe" in p for p in pfade), str(pfade)[:200])
finally:
    ZIEL.unlink(missing_ok=True)
    K.force_reindex(incremental=True)
    end = K.get_stats()
    check("aufgeraeumt: Datei weg und aus dem Index",
          not ZIEL.exists() and end["indexed_files"] == vorher["indexed_files"],
          f"{vorher['indexed_files']} -> {end['indexed_files']}")

print(f"\n{OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
