#!/usr/bin/env python3
"""Gegenprobe zu ``test_eventloop_wissen.py``: jede Sabotage dreht EINEN Fix
zurueck; der Waechter muss jede einzeln mit FAIL (Exit 1) melden.

Sichert jede angefasste Datei vor der Probe in ``~/.gegen-sicherung-evloop``
und nimmt einen Rueckstand eines abgebrochenen Laufs beim Start zurueck.
Nie in einem Sammellauf mitlaufen lassen (patcht den Arbeitsbaum).
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SICHER = Path.home() / ".gegen-sicherung-evloop"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(SICHER)
WAECHTER = ROOT / "tests" / "test_eventloop_wissen.py"

PROBEN = [
    ("Wiki-Index ohne Cache", "backend/wissensgraph.py",
     "        if stand is not None and _wiki_cache is not None and _wiki_cache[0] == stand:\n",
     "        if False:\n"),
    ("Schreiben setzt den Cache nicht", "backend/wissensgraph.py",
     "        if stand is not None:\n            _wiki_cache = (stand, d)\n",
     "        pass\n"),
    ("Cache ohne Datei-Stand (blind)", "backend/wissensgraph.py",
     "        if stand is not None and _wiki_cache is not None and _wiki_cache[0] == stand:\n",
     "        if _wiki_cache is not None:\n"),
    ("FAISS-Uebersicht ohne Cache", "backend/tools/knowledge.py",
     "        if c is not None and c[0] == stand:\n",
     "        if False:\n"),
    ("FAISS-Uebersicht ignoriert den VectorStore", "backend/tools/knowledge.py",
     "    vs = _vector_store\n    if vs is not None:\n        with vs._lock:\n            meta = vs._meta\n",
     "    vs = None\n    if vs is not None:\n        with vs._lock:\n            meta = vs._meta\n"),
    ("get_stats parst wieder selbst", "backend/tools/knowledge.py",
     "        vector_chunks, _pfade = _faiss_uebersicht()\n",
     "        vector_chunks, _pfade = len(json.loads('[]')), set()\n"),
    ("stats wieder in der Loop", "backend/main.py",
     "    data = await asyncio.to_thread(get_stats)\n",
     "    data = get_stats()\n"),
    ("scope wieder in der Loop", "backend/main.py",
     "    return JSONResponse(await asyncio.to_thread(_wissen_scope_daten, user))\n",
     "    return JSONResponse({**_wissen_scope_daten(user), **dict(_editable_groups_for(user) and {})})\n"),
    ("groups wieder in der Loop", "backend/main.py",
     "        paths = await asyncio.to_thread(known_paths_with_disk)\n        data = await asyncio.to_thread(kg.list_groups, paths)\n",
     "        paths = known_paths_with_disk()\n        data = kg.list_groups(paths)\n"),
    ("Wiki-_vermerken wieder in der Loop", "backend/wissensgraph_wiki.py",
     "    await asyncio.to_thread(_vermerken, kid, quellen, datei=datei, modell=modell)\n",
     "    _vermerken(kid, quellen, datei=datei, modell=modell)\n"),
    ("Wiki-Graph wieder in der Loop", "backend/wissensgraph_wiki.py",
     "    g = await asyncio.to_thread(wg.graph)\n",
     "    g = wg.graph()\n"),
    ("Widerspruch-_vermerken wieder in der Loop", "backend/wissensgraph_widerspruch.py",
     "    await asyncio.to_thread(_vermerken, kid, quellen, befunde)\n",
     "    _vermerken(kid, quellen, befunde)\n"),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def zurueck() -> None:
    if not SICHER.exists():
        return
    for rel in DATEIEN:
        s = SICHER / rel
        if s.exists():
            shutil.copy2(s, ROOT / rel)
            if md5(s) != md5(ROOT / rel):
                print(f"ABBRUCH: {rel} nicht byte-gleich wiederhergestellt")
                sys.exit(2)


def lauf() -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                          env=env, timeout=300).returncode


def main() -> int:
    zurueck()                                  # Rueckstand eines abgebrochenen Laufs
    shutil.rmtree(SICHER, ignore_errors=True)
    for rel in DATEIEN:
        ziel = SICHER / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, ziel)
    try:
        if lauf() != 0:
            print("ABBRUCH: Basislauf nicht gruen – keine Gegenprobe deutbar")
            return 2
        beisst = 0
        for name, rel, alt, neu in PROBEN:
            p = ROOT / rel
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != 1:
                print(f"  ANKER  {name}: trifft {t.count(alt)}x (Proben-Mangel)")
                continue
            p.write_text(t.replace(alt, neu), encoding="utf-8")
            try:
                rc = lauf()
            finally:
                shutil.copy2(SICHER / rel, p)
            ok = rc == 1
            beisst += ok
            print(f"  {'BEISST' if ok else 'STUMM '} {name} (Exit {rc})")
        print(f"\nErgebnis: {beisst} von {len(PROBEN)} Proben beissen")
        return 0 if beisst == len(PROBEN) else 1
    finally:
        zurueck()
        shutil.rmtree(SICHER, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
