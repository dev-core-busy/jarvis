#!/usr/bin/env python3
"""Waechter: die Spalte "Groesse" in /wissen -> Mein Wissen (2026-09-27).

`_wissen_groessen` und `_wissen_absolut` werden per `ast` aus backend/main.py
geschnitten und WIRKLICH AUSGEFUEHRT – gegen echte Dateien in einem
Wegwerf-Verzeichnis. Ob eine Groesse stimmt, ob ein stummes Netzlaufwerk die
Liste aufhaelt oder ob "unbekannt" zu 0 wird, kann eine Quelltext-Pruefung
nicht beantworten.

Geprueft wird die EIGENSCHAFT:
  1. relative Manifest-Schluessel (data/…) und abgestreifte absolute
     (`mnt/…`, siehe knowledge_groups._rel) finden beide ihre Datei
  2. 0 Byte ist 0, eine fehlende Datei ist KEIN Eintrag (-> None, nie 0)
  3. ein stummer Einhaengepunkt wird EINMAL gefragt und nicht durchlaufen
  4. ein haengender Zugriff haelt den Aufruf nicht auf (Zeitbudget)
  5. der Cache spart den zweiten Durchlauf
  6. der Endpunkt reicht die Groesse wirklich durch (Regel ueber den AST)

Exit 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"

res: list[bool] = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


def abbruch(t):
    print(f"\033[31mABBRUCH: {t}\033[0m")
    sys.exit(2)


BAUM = ast.parse(MAIN.read_text(encoding="utf-8"))
FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in ("_wissen_groessen", "_wissen_absolut", "wissen_files"):
    if name not in FN:
        abbruch(f"{name} nicht in backend/main.py")
KONST = {}
for n in BAUM.body:
    # Zuweisung mit UND ohne Typangabe (`_X: dict = {}` ist ein AnnAssign).
    ziel = (n.targets[0] if isinstance(n, ast.Assign) and len(n.targets) == 1
            else n.target if isinstance(n, ast.AnnAssign) else None)
    if isinstance(ziel, ast.Name) and ziel.id.startswith("_WISSEN_GROESSE_"):
        KONST[ziel.id] = n

# ── Sandkasten ────────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="wgroesse_"))
PROJ = TMP / "proj"
(PROJ / "data" / "rag" / "a").mkdir(parents=True)
(PROJ / "data" / "rag" / "a" / "drei.md").write_bytes(b"abc")
(PROJ / "data" / "rag" / "a" / "leer.md").write_bytes(b"")
# "Ausserhalb von PROJECT_ROOT": ein Geschwisterverzeichnis, dessen erster
# Pfadteil unter PROJ NICHT existiert – so wie `mnt` unter /opt/jarvis.
AUSSEN = TMP / "aussen" / "share_1"
AUSSEN.mkdir(parents=True)
(AUSSEN / "gross.pdf").write_bytes(b"x" * 5000)
AUSSEN_KEY = str(AUSSEN / "gross.pdf").lstrip("/")   # so schreibt _rel() den Schluessel
if (PROJ / AUSSEN_KEY.split("/", 1)[0]).exists():
    abbruch("Sandkasten: erster Pfadteil des Aussen-Schluessels existiert unter PROJ")

safe_aufrufe: list[str] = []
safe_antwort = {"stumm": set(), "verzoegerung": 0.0}


def _safe_exists_attrappe(path, timeout: float = 2.0) -> bool:
    safe_aufrufe.append(str(path))
    if safe_antwort["verzoegerung"]:
        time.sleep(safe_antwort["verzoegerung"])
    return str(path) not in safe_antwort["stumm"]


# `backend.tools.knowledge` als Attrappe mit der ECHTEN Signatur – der echte
# Import zoege das ganze Wissens-Modul samt Konfiguration nach sich.
kn = types.ModuleType("backend.tools.knowledge")
kn.PROJECT_ROOT = PROJ
kn._safe_exists = _safe_exists_attrappe
sys.modules.setdefault("backend", types.ModuleType("backend"))
sys.modules.setdefault("backend.tools", types.ModuleType("backend.tools"))
sys.modules["backend.tools.knowledge"] = kn

scandir_zaehler = {"n": 0}


class _OsZaehler:
    """`os` mit zaehlendem scandir – alles andere geht an das echte Modul."""
    def __getattr__(self, name):
        return getattr(os, name)

    def scandir(self, p):
        scandir_zaehler["n"] += 1
        return os.scandir(p)


NS = {"Path": Path, "time": time, "asyncio": asyncio, "os": _OsZaehler(), "threading": threading}
knoten = [ast.parse(ast.unparse(KONST[k])).body[0] for k in sorted(KONST)]
for name in ("_wissen_absolut", "_wissen_groessen"):
    kopie = ast.parse(ast.unparse(FN[name])).body[0]
    kopie.decorator_list = []
    knoten.append(kopie)
exec(compile(ast.fix_missing_locations(ast.Module(body=knoten, type_ignores=[])), "<main-schnitt>", "exec"), NS)
if "_WISSEN_GROESSE_CACHE" not in NS or "_wissen_groessen" not in NS:
    abbruch("Schnitt unvollstaendig")

groessen = NS["_wissen_groessen"]
absolut = NS["_wissen_absolut"]


def lauf(pfade):
    return asyncio.run(groessen(pfade))


def frisch():
    NS["_WISSEN_GROESSE_CACHE"].clear()
    safe_aufrufe.clear()
    scandir_zaehler["n"] = 0
    safe_antwort["stumm"] = set()
    safe_antwort["verzoegerung"] = 0.0


try:
    abschnitt("1 – beide Schluesselformen finden ihre Datei")
    check("relativer Schluessel -> unter PROJECT_ROOT",
          absolut("data/rag/a/drei.md") == PROJ / "data/rag/a/drei.md", absolut("data/rag/a/drei.md"))
    check("abgestreifter absoluter Schluessel -> absolut (nicht unter PROJECT_ROOT)",
          absolut(AUSSEN_KEY) == AUSSEN / "gross.pdf", absolut(AUSSEN_KEY))
    frisch()
    g = lauf(["data/rag/a/drei.md", AUSSEN_KEY])
    check("Positivkontrolle: 3 Byte richtig", g.get("data/rag/a/drei.md") == 3, g)
    check("Datei ausserhalb von PROJECT_ROOT: 5000 Byte", g.get(AUSSEN_KEY) == 5000, g)

    abschnitt("2 – 0 ist 0, fehlend ist None")
    frisch()
    g = lauf(["data/rag/a/leer.md", "data/rag/a/gibtsnicht.md", "data/rag/weg/x.md"])
    check("leere Datei -> 0 (nicht weggelassen)", g.get("data/rag/a/leer.md", "fehlt") == 0, g)
    check("fehlende Datei -> kein Eintrag (Endpunkt macht None daraus)",
          "data/rag/a/gibtsnicht.md" not in g and "data/rag/weg/x.md" not in g, g)

    abschnitt("3 – stummer Einhaengepunkt")
    # Ein Pfad /mnt/<basis>/<share> wird vor dem Durchlauf ueber _safe_exists
    # gefragt. Die Attrappe meldet ihn stumm -> kein scandir dort.
    frisch()
    mp = "/mnt/rag/share_9"
    safe_antwort["stumm"] = {mp}
    g = lauf(["mnt/rag/share_9/a.pdf", "mnt/rag/share_9/unter/b.pdf", "mnt/rag/share_9/unter/c.pdf",
              "data/rag/a/drei.md"])
    check("Einhaengepunkt gefragt", mp in safe_aufrufe, safe_aufrufe)
    check("… genau EINMAL, nicht je Verzeichnis", safe_aufrufe.count(mp) == 1, safe_aufrufe)
    check("… und dort nichts durchlaufen (nur das lokale Verzeichnis)", scandir_zaehler["n"] == 1,
          scandir_zaehler["n"])
    check("die lokale Datei kommt trotzdem", g.get("data/rag/a/drei.md") == 3, g)

    abschnitt("4 – ein haengender Zugriff haelt den Aufruf nicht auf")
    frisch()
    NS["_WISSEN_GROESSE_BUDGET"] = 0.3
    safe_antwort["verzoegerung"] = 3.0    # "haengt" am Einhaengepunkt
    t0 = time.monotonic()
    g = lauf(["mnt/rag/share_8/x.pdf"])
    dauer = time.monotonic() - t0
    check("kehrt nach Budget zurueck (< 1,5 s statt 3 s)", dauer < 1.5, f"{dauer:.2f} s")
    check("… ohne Groesse fuer die haengende Datei", "mnt/rag/share_8/x.pdf" not in g, g)
    NS["_WISSEN_GROESSE_BUDGET"] = 3.0
    time.sleep(3.1)                        # Daemon-Thread auslaufen lassen

    abschnitt("5 – Cache")
    frisch()
    lauf(["data/rag/a/drei.md"])
    n1 = scandir_zaehler["n"]
    g = lauf(["data/rag/a/drei.md"])
    check("Positivkontrolle: erster Lauf durchlief das Verzeichnis", n1 == 1, n1)
    check("zweiter Lauf ohne Durchlauf, gleicher Wert",
          scandir_zaehler["n"] == 1 and g.get("data/rag/a/drei.md") == 3, (scandir_zaehler["n"], g))

    abschnitt("6 – der Endpunkt reicht die Groesse durch (AST)")
    ep = FN["wissen_files"]
    ruft = [c for c in ast.walk(ep) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name) and c.func.id == "_wissen_groessen"]
    check("wissen_files ruft _wissen_groessen", len(ruft) == 1, len(ruft))
    awaited = [a for a in ast.walk(ep) if isinstance(a, ast.Await)
               and isinstance(a.value, ast.Call) and getattr(a.value.func, "id", "") == "_wissen_groessen"]
    check("… mit await (sonst steht ein Coroutine-Objekt in der Antwort)", len(awaited) == 1)
    setzt = [z for z in ast.walk(ep) if isinstance(z, ast.Assign)
             and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                     and t.slice.value == "size" for t in z.targets)]
    check("… und setzt das Feld 'size' je Datei", len(setzt) == 1, len(setzt))
    # `groessen.get(pfad)` OHNE Vorgabewert: eine nicht ermittelte Groesse ist
    # None, und die Oberflaeche zeigt dafuer einen Strich. Ein `get(p, 0)`
    # behauptete "leere Datei".
    gets = [c for z in setzt for c in ast.walk(z.value) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute) and c.func.attr == "get"]
    check("… ohne Vorgabewert (unbekannt bleibt None, wird nie 0)",
          len(gets) == 1 and len(gets[0].args) == 1 and not gets[0].keywords,
          [ast.unparse(g) for g in gets])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n\033[1mErgebnis: {sum(res)}/{len(res)}\033[0m")
sys.exit(0 if all(res) else 1)
