#!/usr/bin/env python3
"""Vier Fixes aus dem /tracks-Vorfall vom 2026-08-19/20.

GEMELDET: Ein Lauf der Ablage "Tabellen zusammenfuehren" schrieb "Da der
xlsx_merge auf die Dateien in data/documents/ keinen Lesezugriff hat ..." – eine
technisch klingende Begruendung fuer einen Fehler, den es nicht gab. Aus den
Protokollen auf ECHT nachgemessen:

  1. RINGPUFFER: der Lauf machte 54 Werkzeugaufrufe, `xlsx_edit` war der 54.
     Der Ergebnis-Sammler hatte einen Deckel von 40 und fuellte VON VORNE – die
     `/api/documents/`-URL des Ergebnisses steht aber immer im LETZTEN Ergebnis.
     Folge: die fertige Datei (35 KB) lag in data/documents, `dateien` im
     Protokoll war LEER, kein Download-Chip.
  2. BESTAND: die Ablage stand auf `einzeln`, ihr Prompt verlangte "zwei Excel
     Dateien (Master und Slave)". Nichts im Auftrag sagte, wie viele Dateien
     vorliegen -> das Modell hat die zweite in data/documents GESUCHT und Namen
     samt Capability-Id ERFUNDEN.
  3. EIN WEG ZUR DATEI: der Auftrag nannte zusaetzlich "Ablage: '<name>' (fuer
     office_read / filesystem)" – die Einladung, dort zu greifen.
  4. VORHALTEZEIT: `cleanup_old` erfasste nur Capability-Dateien. Auf ECHT:
     76 davon (13,6 MB) unterlagen der Frist, 61 Roh-Dateien (95,4 MB) nicht.

Laeuft OHNE fastapi: die Funktionen werden per Quelltext geladen,
`backend.config` wird NICHT importiert (der echte Import migriert Profile und
schriebe die Live-settings.json zurueck).

Aufruf:  python3 tests/test_tracks_ergebnis.py
"""
from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def pruefe(name, bedingung, detail=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  \033[32mOK\033[0m   %s" % name)
    else:
        fail += 1
        print("  \033[31mFAIL\033[0m %s%s" % (name, "  ->  " + str(detail) if detail else ""))


def quelle(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def nur_code(t: str) -> str:
    """Docstrings und Kommentare entfernen.

    PFLICHT fuer jede Pruefung an dieser Datei: die Begruendungen nennen die
    alten Fassungen woertlich ("if len(ergebnisse) >= _ERGEBNIS_MAX"). Ohne
    diesen Schritt liest der Waechter seine eigene Erklaerung und ist gruen,
    obwohl der Code falsch ist – der Fall ist in diesem Projekt neunmal
    aufgetreten.
    """
    t = re.sub(r'"""[\s\S]*?"""', "", t)
    t = re.sub(r"^[ \t]*#.*$", "", t, flags=re.M)
    t = re.sub(r"(?<![:\w])#(?!\{).*$", "", t, flags=re.M)
    return t


RUNNER = quelle("backend/short_tracks_runner.py")
RUNNER_C = nur_code(RUNNER)
TRACKS = quelle("backend/short_tracks.py")
DOCS = quelle("backend/documents.py")

# ══ 1. Ringpuffer ═══════════════════════════════════════════════════════════
abschnitt("1. Ergebnis-Sammler: Ringpuffer statt Deckel-von-vorne")

pruefe("kein frueher Ausstieg bei erreichtem Deckel",
       ">= _ERGEBNIS_MAX" not in RUNNER_C and "> _ERGEBNIS_MAX" not in RUNNER_C,
       "alter Deckel noch im Code")
pruefe("behaelt die LETZTEN Ergebnisse (negativer Slice)",
       "del ergebnisse[:-_ERGEBNIS_MAX]" in RUNNER_C)

# Den Hook wirklich ausfuehren – Quelltext-Pruefung allein beweist nichts.
m = re.search(r"( *)def _ergebnis\(name: str, text\) -> None:\n((?:\1 +.*\n|\n)+)", RUNNER)
pruefe("Hook-Funktion im Quelltext gefunden", m is not None)
if m:
    koerper = "\n".join(l[len(m.group(1)):] for l in m.group(0).splitlines())
    umgebung = {"_ERGEBNIS_MAX": 40, "ergebnisse": []}
    exec(compile(koerper, "<hook>", "exec"), umgebung)
    hook = umgebung["_ergebnis"]
    liste = umgebung["ergebnisse"]
    # 54 Aufrufe wie im echten Lauf; die URL steht im letzten.
    for i in range(53):
        hook("xlsx_read_range", "Zeile %d" % i)
    hook("xlsx_edit", "Datei erstellt [Download](/api/documents/abc__ergebnis.xlsx)")
    pruefe("nach 54 Aufrufen genau 40 gemerkt", len(liste) == 40, len(liste))
    pruefe("das LETZTE Ergebnis ist dabei (die Chip-URL)",
           any("/api/documents/abc__ergebnis.xlsx" in x for x in liste),
           "URL verloren – kein Download-Chip")
    pruefe("das erste (belanglose) ist herausgefallen",
           not any(x == "Zeile 0" for x in liste))

# ══ 2. Bestand im Auftrag ═══════════════════════════════════════════════════
abschnitt("2. Der Auftrag nennt, WIE VIELE Dateien vorliegen")

pruefe("_bestand_text existiert", "def _bestand_text(" in RUNNER_C)
pruefe("wird in den Vorspann eingesetzt", "bestand=_bestand_text(teile)" in RUNNER_C)
pruefe("Vorspann hat den Platzhalter", "{bestand}" in RUNNER)

# Funktion ausfuehren.
mod = ast.parse(RUNNER)
fn = next((n for n in mod.body if isinstance(n, ast.FunctionDef)
           and n.name == "_bestand_text"), None)
pruefe("_bestand_text als Funktion geparst", fn is not None)
if fn:
    hilf = next((n for n in mod.body if isinstance(n, ast.FunctionDef)
                 and n.name == "_markensicher"), None)
    umg: dict = {"re": re}
    if hilf:
        exec(compile(ast.Module(body=[hilf], type_ignores=[]), "<h>", "exec"), umg)
    else:
        umg["_markensicher"] = lambda x: str(x or "")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<f>", "exec"), umg)
    bestand = umg["_bestand_text"]

    eine = bestand([{"name": "Monatsstatistik.xlsx", "art": "datei"}])
    pruefe("nennt die Anzahl bei einer Datei", "GENAU 1 Datei" in eine, eine[:80])
    pruefe("nennt den Dateinamen", "Monatsstatistik.xlsx" in eine)
    pruefe("sagt ausdruecklich, dass es keine weiteren gibt",
           "MEHR GIBT ES NICHT" in eine)
    pruefe("verbietet das Raten von Dateinamen",
           "rate keine Dateinamen" in eine or "Suche sie nicht" in eine)
    # DER KERN: das Modell soll "nicht gefunden" nicht als Rechteproblem deuten.
    pruefe("stellt klar: 'nicht gefunden' ist kein fehlendes Zugriffsrecht",
           "Zugriffsrecht" in eine)
    zwei = bestand([{"name": "a.xlsx", "art": "datei"}, {"name": "b.xlsx", "art": "datei"}])
    pruefe("zaehlt zwei Dateien richtig", "GENAU 2 Datei" in zwei, zwei[:80])
    leer = bestand([])
    pruefe("kein Inhalt wird benannt", "kein Inhalt" in leer)

# ══ 3. Genau EIN Weg zur Datei ══════════════════════════════════════════════
abschnitt("3. Der Auftrag nennt nur den /tmp-Pfad")

pruefe("kein 'fuer office_read / filesystem'-Hinweis mehr",
       "fuer office_read / filesystem" not in RUNNER_C)
pruefe("Ablagename nur noch als Rueckfall (elif)",
       re.search(r"elif t\.get\(\"ablage\"\)", RUNNER_C) is not None)
pruefe("sagt, dass es keinen zweiten Weg gibt",
       "keinen zweiten Weg" in RUNNER)

# ══ 4. Vorhaltezeit fuer Uploads ════════════════════════════════════════════
abschnitt("4. Vorhaltezeit erfasst auch hochgeladene Dateien")

DOCS_C = nur_code(DOCS)
pruefe("_unterliegt_frist existiert", "def _unterliegt_frist(" in DOCS_C)
pruefe("cleanup_old benutzt es", "_unterliegt_frist(p.name" in DOCS_C)
pruefe("filtert nicht mehr allein auf is_capability",
       "not is_capability(p.name)" not in DOCS_C)

# Echt ausfuehren – gegen ein Wegwerf-Verzeichnis.
sys.modules.pop("backend.documents", None)
tmp = Path(tempfile.mkdtemp(prefix="tracks_docs_"))
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_docs_probe", ROOT / "backend" / "documents.py")
    dm = importlib.util.module_from_spec(spec)
    # config wird nur in retention_days() gebraucht -> Frist direkt uebergeben.
    sys.modules["_docs_probe"] = dm
    spec.loader.exec_module(dm)
    # SANDKASTEN-SCHRANKE: niemals im echten data/documents arbeiten.
    dm.DOCS_DIR = tmp
    dm._REGISTRY = tmp / ".owners.json"
    if Path(dm.DOCS_DIR).resolve() != tmp.resolve():
        print("ABBRUCH: Sandkasten nicht gesetzt"); sys.exit(2)

    alt = time.time() - 40 * 86400
    dateien = {
        "a" * 32 + "__ergebnis.xlsx": ("cap", True),          # Capability -> weg
        "IBSv3_Monatsstatistik.xlsx": ("upload", True),        # Upload      -> weg
        "fremd_ohne_eintrag.xlsx": (None, False),              # kein Eintrag-> bleibt
    }
    for n, (art, _) in dateien.items():
        (tmp / n).write_bytes(b"x" * 100)
        import os
        os.utime(tmp / n, (alt, alt))
        if art == "upload":
            dm.register_upload(n, "andreas.bender")
        elif art == "cap":
            dm.register(n, "andreas.bender")
    # Eine junge Upload-Datei muss bleiben.
    (tmp / "heute_hochgeladen.xlsx").write_bytes(b"y" * 50)
    dm.register_upload("heute_hochgeladen.xlsx", "andreas.bender")

    entfernt, bytes_frei = dm.cleanup_old(days=30)
    pruefe("Capability-Datei entfernt", not (tmp / ("a" * 32 + "__ergebnis.xlsx")).exists())
    pruefe("alte HOCHGELADENE Datei entfernt (der Fix)",
           not (tmp / "IBSv3_Monatsstatistik.xlsx").exists())
    pruefe("Datei OHNE Registry-Eintrag bleibt liegen",
           (tmp / "fremd_ohne_eintrag.xlsx").exists(),
           "Raten beim Loeschen ist die schlechteste Wahl")
    pruefe("junge Upload-Datei bleibt", (tmp / "heute_hochgeladen.xlsx").exists())
    pruefe("Zaehler stimmt", entfernt == 2, entfernt)
    pruefe("Registry laeuft nicht voll (Eintraege ohne Datei weg)",
           "IBSv3_Monatsstatistik.xlsx" not in dm._load())
    # 0 = dauerhaft: nichts darf verschwinden.
    (tmp / "noch_eine.xlsx").write_bytes(b"z")
    import os as _os
    _os.utime(tmp / "noch_eine.xlsx", (alt, alt))
    dm.register_upload("noch_eine.xlsx", "andreas.bender")
    e2, _ = dm.cleanup_old(days=0)
    pruefe("Frist 0 = dauerhaft, nichts entfernt", e2 == 0 and (tmp / "noch_eine.xlsx").exists())
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ══ 5. Widerspruch Prompt <-> Verarbeitungsart ══════════════════════════════
abschnitt("5. 'einzeln' + Prompt fuer mehrere Dateien wird beanstandet")

fnv = re.search(r"def prompt_verlangt_mehrere\(prompt: str\) -> bool:[\s\S]*?\n    return [^\n]+\n",
                TRACKS)
pruefe("prompt_verlangt_mehrere existiert", fnv is not None)
if fnv:
    umg2: dict = {"re": re}
    for name in ("_DATEI_WORT", "_MEHRERE_MUSTER"):
        mm = re.search(r"^%s = (?:re\.compile\()?[\s\S]*?\n(?=\n|[A-Za-z_])" % name,
                       TRACKS, re.M)
        pruefe("Muster %s geladen" % name, mm is not None)
        if mm:
            exec(compile(mm.group(0), "<r>", "exec"), umg2)
    exec(compile(fnv.group(0), "<f>", "exec"), umg2)
    vm = umg2["prompt_verlangt_mehrere"]

    # DER GEMELDETE WORTLAUT.
    echt = ("Du benötigst zwei Excel Dateien. Eine ist Master und eine ist Slave. "
            "Die Master Tabelle enthält eine Gesamtübersicht")
    pruefe("erkennt den gemeldeten Prompt", vm(echt) is True)
    for muss in ("Die Master Tabelle und die Slave Tabelle zusammenfuehren",
                 "Fuehre beide Tabellen zusammen",
                 "mehrere Dokumente vergleichen",
                 "2 Dateien abgleichen",
                 "vergleiche drei Mappen"):
        pruefe("erkennt: %r" % muss[:40], vm(muss) is True, muss)
    # FEHLALARME SIND HIER TEUER: die Meldung blockiert das Speichern, und eine
    # Schranke, die man gewohnheitsmaessig umgeht, schuetzt nichts mehr. Die
    # ersten zwei Faelle hat der Test in der ersten Fassung wirklich gefunden.
    for harmlos in ("Extrahiere die Adresse aus dem Auftrag",
                    "Fasse das Dokument in drei Saetzen zusammen",
                    "Erzeuge zwei Diagramme aus der Tabelle",
                    "Nenne die drei wichtigsten Punkte des Dokuments",
                    "Erstelle vier Folien aus der Tabelle",
                    "Pruefe die Tabelle auf Fehler",
                    "Liste alle Positionen der Rechnung"):
        pruefe("kein Fehlalarm: %r" % harmlos[:38], vm(harmlos) is False, harmlos)

pruefe("_pruefe lehnt den Widerspruch ab",
       "prompt_verlangt_mehrere(prompt)" in nur_code(TRACKS))
pruefe("Meldung nennt BEIDE Auswege",
       "alle gemeinsam" in TRACKS and "auf eine Datei umformulieren" in TRACKS)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
