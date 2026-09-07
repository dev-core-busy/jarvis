#!/usr/bin/env python3
"""Waechter: eine ABGEHAENGTE Freigabe streift ihr Wissen nicht aus dem Index.

⚠ AM 2026-09-07 BEZAHLT (selbst ausgeloest). `_safe_exists()` schuetzt gegen
ein TOTES Netzlaufwerk - eines, das blockiert und in den Timeout laeuft. Ein
Einhaengepunkt OHNE Mount ist aber ein ganz gewoehnliches, LEERES Verzeichnis,
das sofort antwortet: `_safe_exists` sagt dazu voellig zu Recht True.

Damit galt die Freigabe als "erreichbar und geleert", und der ausdrueckliche
Neuaufbau entfernte SAEMTLICHE Chunks ihres Wissens als verwaist.
GEMESSEN auf DEV: 1208 Chunks aus zwei OneNote-Dateien, weil
/mnt/jarvis-kb/share_0|1 nach einem Neustart nicht wieder eingehaengt waren -
und der Dateiserver war die ganze Zeit erreichbar (Ping ok, Port 445 offen).

Die zweite Stelle ist die gefaehrlichere: im Voll-Neuaufbau haette
`len(alive) == len(folders)` gegolten und `vs.clear()` ALLES weggeworfen.

Gemessen wird die EIGENSCHAFT an echten Verzeichnissen - die Funktionen laufen
WIRKLICH, nichts wird nachgebaut.
"""
import ast
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    if not isinstance(bed, bool):
        print(f"\033[31mABBRUCH\033[0m: check('{name}') bekam {type(bed).__name__} statt bool")
        sys.exit(2)
    print(("  \033[32m✓\033[0m " if bed else "  \033[31m✗\033[0m ") + name)
    if bed:
        OK += 1
    else:
        FAIL += 1


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = io.open(os.path.join(REPO, "backend/tools/knowledge.py"), encoding="utf-8").read()
BAUM = ast.parse(Q)

# ── Die Funktionen SCHNEIDEN und WIRKLICH ausfuehren ─────────────────────
# Der Import von backend.tools.knowledge zieht FAISS und
# sentence-transformers mit - der Waechter soll ueberall laufen.
NOETIG = {"_bounded_call", "_safe_exists", "_ordner_abgehaengt", "_nutzbare_ordner"}
teile = [n for n in BAUM.body
         if isinstance(n, ast.FunctionDef) and n.name in NOETIG]
gefunden = {n.name for n in teile}
if gefunden != NOETIG:
    for n in sorted(NOETIG - gefunden):
        check(f"knowledge.py kennt {n}()", False)
    print(f"\n\033[1m{OK} OK, {FAIL} FAIL\033[0m  (aelterer Stand - Rest uebersprungen)")
    sys.exit(1)

import logging
import threading
import time

NS = {"os": os, "time": time, "threading": threading, "Path": Path,
      "_log": logging.getLogger("test"), "_avail_down_until": {}}
exec(compile(ast.Module(body=teile, type_ignores=[]), "<schnitt>", "exec"), NS)
abgehaengt = NS["_ordner_abgehaengt"]
nutzbar = NS["_nutzbare_ordner"]

SAND = Path(tempfile.mkdtemp(prefix="abgeh_"))
leer = SAND / "share_1"          # der nicht eingehaengte Einhaengepunkt
voll = SAND / "share_0"          # eine wirklich eingehaengte Freigabe
lokal = SAND / "data_knowledge"  # gewoehnlicher lokaler Ordner
neu = SAND / "frisch"            # leer, aber noch nie indiziert
for d in (leer, voll, lokal, neu):
    d.mkdir(parents=True)
(voll / "handbuch.pdf").write_text("x", encoding="utf-8")
(lokal / "notiz.md").write_text("x", encoding="utf-8")

INDEXED = [str(leer / "OneNote-Jasmin" / "Allgemein.one"),
           str(leer / "OneNote-Jasmin" / "Informationen.one"),
           str(voll / "handbuch.pdf"),
           str(lokal / "notiz.md")]

print("\033[1m1. Der gemeldete Fall\033[0m")
g_leer = abgehaengt(leer, INDEXED)
check("⚠ leerer Einhaengepunkt MIT Index-Eintraegen gilt als abgehaengt",
      bool(g_leer))
check("eine wirklich eingehaengte Freigabe nicht",
      abgehaengt(voll, INDEXED) is None)
check("ein gewoehnlicher Ordner mit Inhalt nicht",
      abgehaengt(lokal, INDEXED) is None)
check("⚠ ein LEERER Ordner OHNE Index-Eintraege nicht (nichts zu verlieren)",
      abgehaengt(neu, INDEXED) is None)
g_weg = abgehaengt(SAND / "gibtsnicht", [str(SAND / "gibtsnicht" / "x.pdf")])
check("nicht lesbar -> wie abgehaengt (fail-safe)", bool(g_weg))
# ⚠ ZWEI BEFUNDE, ZWEI MELDUNGEN: "leer" und "nicht lesbar" verlangen vom
# Administrator verschiedene Handlungen. Eine gemeinsame Meldung schickt ihn
# im Rechtefall in die falsche Richtung.
check("der GRUND wird unterschieden: leer gegen nicht lesbar",
      isinstance(g_leer, str) and isinstance(g_weg, str) and g_leer != g_weg)
check("der leere Ordner nennt die Freigabe als Vermutung",
      "Netzfreigabe" in str(g_leer))
check("der unlesbare nennt Rechte/Timeout",
      "Rechte" in str(g_weg) or "Timeout" in str(g_weg))

print("\n\033[1m2. _nutzbare_ordner: EINE Stelle fuer beide Aufrufer\033[0m")
ordner = [lokal, voll, leer]
n = nutzbar(ordner, INDEXED)
check("der abgehaengte Ordner faellt heraus", leer not in n)
check("die erreichbaren bleiben", lokal in n and voll in n)
check("⚠ streng=False laesst die Pruefung aus (Suchpfad, kein listdir je Suche)",
      leer in nutzbar(ordner, INDEXED, streng=False))
check("ein nicht existierender Ordner faellt weiter heraus",
      (SAND / "weg") not in nutzbar([SAND / "weg"], []))

print("\n\033[1m3. Beide Aufrufstellen benutzen sie - als REGEL\033[0m")
# Jede Zuweisung an `alive` in dieser Datei muss ueber _nutzbare_ordner gehen.
zuweisungen = []
for n_ in ast.walk(BAUM):
    if isinstance(n_, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "alive" for t in n_.targets):
        zuweisungen.append(n_)
check(f"es gibt {len(zuweisungen)} alive-Zuweisungen (erwartet >=2)", len(zuweisungen) >= 2)
ueber_helfer = [z for z in zuweisungen
                if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                       and c.func.id == "_nutzbare_ordner" for c in ast.walk(z))]
check("⚠ JEDE alive-Zuweisung geht ueber _nutzbare_ordner",
      len(ueber_helfer) == len(zuweisungen))
check("keine davon ruft _safe_exists direkt in einer Comprehension",
      not any(any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                  and c.func.id == "_safe_exists" for c in ast.walk(z))
              for z in zuweisungen))

print("\n\033[1m4. Der Voll-Neuaufbau darf nicht blind leeren\033[0m")
# ⚠ DIE FUNKTION WIRD GESUCHT, NICHT GERATEN: `vs.clear()` steht in
# `_do_force_reindex`, nicht in `force_reindex` - ein geratener Name meldet
# einen Fehler, den es nicht gibt (Register).
# ⚠ UND ER WIRD UEBER DEN AST GESUCHT, NICHT ALS TEXT: der Wortlaut
# "vs.clear()" steht in drei Docstrings und mehreren Kommentaren, die genau
# diese Stelle ERKLAEREN. Eine Textsuche liest also die eigene Begruendung
# und meldet drei Kandidaten statt einem (Register, x-ter Fall).
def _ruft_vs_clear(knoten) -> bool:
    for c in ast.walk(knoten):
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "clear"
                and isinstance(c.func.value, ast.Name) and c.func.value.id == "vs"):
            return True
    return False


kandidaten = [n_ for n_ in ast.walk(BAUM)
              if isinstance(n_, (ast.FunctionDef, ast.AsyncFunctionDef))
              and _ruft_vs_clear(n_)]
check(f"genau eine Funktion ruft vs.clear() (gefunden: "
      f"{[k.name for k in kandidaten]})", len(kandidaten) == 1)
rumpf = ast.get_source_segment(Q, kandidaten[0]) if kandidaten else ""
# ⚠ Auch die REIHENFOLGE ueber Zeilennummern des AST, nicht ueber `find`:
# der erklaerende Kommentar nennt "vs.clear()" VOR dem Aufruf von
# _nutzbare_ordner - eine Textsuche vergleicht damit Kommentar gegen Code.
def _zeilen(knoten, praedikat):
    return [c.lineno for c in ast.walk(knoten) if praedikat(c)]


z_alive = _zeilen(kandidaten[0] if kandidaten else BAUM,
                  lambda c: isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                  and c.func.id == "_nutzbare_ordner") if kandidaten else []
# ⚠ Das Praedikat muss den AUFRUF-Knoten treffen, nicht irgendeinen Knoten,
# der ihn ENTHAELT: `_ruft_vs_clear` laeuft rekursiv und ist fuer die Funktion
# selbst wahr - dann waere `min(z_clear)` die Zeile der Funktionsdefinition.
z_clear = _zeilen(kandidaten[0],
                  lambda c: isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                  and c.func.attr == "clear" and isinstance(c.func.value, ast.Name)
                  and c.func.value.id == "vs") if kandidaten else []
check("vs.clear() steht HINTER der Erreichbarkeits-Pruefung",
      bool(z_alive) and bool(z_clear) and min(z_alive) < min(z_clear))
check("die Abbruch-Schranke 'kein Ordner erreichbar' steht noch",
      "Kein Wissensordner erreichbar" in rumpf)

print("\n\033[1m5. Der Fall wird PROTOKOLLIERT (sonst bemerkt ihn niemand)\033[0m")
q_helfer = ast.get_source_segment(Q, next(
    n_ for n_ in BAUM.body if isinstance(n_, ast.FunctionDef) and n_.name == "_nutzbare_ordner")) or ""
check("es gibt eine Warnung mit dem Ordnernamen",
      "_log.warning" in q_helfer and "%s" in q_helfer)
check("sie nennt den GRUND als eigenen Platzhalter",
      q_helfer.count("%s") >= 2 and "grund" in q_helfer)

import shutil
shutil.rmtree(SAND, ignore_errors=True)
print(f"\n\033[1m{OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
