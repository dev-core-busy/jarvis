#!/usr/bin/env python3
"""Waechter: dieselbe Aufgabe wird nicht zweimal gelernt, Selbstauskunft gar nicht.

⚠ DER GEMELDETE FEHLER (DEV, 2026-09-07, Betreiber): unter "gelerntes Wissen"
stand NEUNMAL dieselbe Zeile
  "Gelernt: Erstelle eine PowerPoint-Praesentation mit 6 Folien ueber die
   Vorteile von Prozess..."
mit der Frage "wieso steht da immer wieder das gleiche?".

GEMESSEN am echten DEV-Bestand:
  - 9 der 10 Notizen: derselbe Auftrag, entstanden in SECHS MINUTEN
    (04.09., 07:38-07:44) aus wiederholten Testlaeufen.
  - ueber 684 Konversationen: 68 % aller Laeufe wiederholen eine schon
    gesehene Aufgabe ("mal mir ein bild" 99x, "testfrage" 80x).
  - von 108 Faktenzeilen des Gesamtbestands reden 22 ueber Jarvis SELBST;
    "Vorlagenpfad ist /opt/jarvis/data/vorlagen/standard.pptx" steht
    SECHSMAL darin, jedes Mal anders formuliert.

⚠ ZWEI INHALTSBASIERTE ANSAETZE WURDEN GEMESSEN UND VERWORFEN - deshalb
vergleicht der Code die AUFGABE und nicht den INHALT:
  - lexikalisch: 7 von 51 Zeilen erkannt, 0 Dateien uebersprungen
  - semantisch (e5): Dubletten median 0.857 gegen fremd 0.823 - Ueberlappung

Der Substanz-Filter vom 2026-09-06 kann diesen Fall NICHT fangen: die Zeilen
sind wohlgeformte Fakten. Andere Fehlerklasse.

Gemessen wird die EIGENSCHAFT an den ECHTEN Texten - die Funktionen laufen
WIRKLICH, nichts wird nachgebaut.
"""
import ast
import asyncio
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    if not isinstance(bed, bool):
        print(f"\033[31mABBRUCH\033[0m: check('{name}') bekam {type(bed).__name__}, "
              "kein bool - Argumente vertauscht?")
        sys.exit(2)
    print(("  \033[32m✓\033[0m " if bed else "  \033[31m✗\033[0m ") + name)
    if bed:
        OK += 1
    else:
        FAIL += 1


def sicher(fn, *a, **k):
    """Ruft auf, ohne dass ein Wurf den Lauf ohne Bilanz abbrechen laesst."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"<WURF {type(e).__name__}: {e}>"


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = io.open(os.path.join(REPO, "backend/learning.py"), encoding="utf-8").read()

# ── Modul laden, aber in einem SANDKASTEN ────────────────────────────────
# ⚠ Ohne diese Schranke schreibt der Test in den ECHTEN Wissensbestand.
import tempfile
from pathlib import Path

SAND = Path(tempfile.mkdtemp(prefix="lerndedup_"))
import backend.learning as L                                  # noqa: E402

# ⚠ NAMENS-GUARD GANZ OBEN. Ohne ihn bricht der Lauf gegen einen aelteren
# Stand mit AttributeError ab - OHNE Bilanzzeile, und "konnte nicht laufen"
# ist dann von "bestanden" nicht zu unterscheiden (Register). Zwei
# Gegenproben sind genau daran vorbeigelaufen.
_NOETIG = ("task_kennung", "bereits_gelernt", "wiederhol_fenster_tage",
           "_ohne_selbstbezug", "_eigene_pfade", "_redet_ueber_sich_selbst")
_fehlt = [n for n in _NOETIG if not hasattr(L, n)]
if _fehlt:
    for n in _fehlt:
        check(f"backend/learning.py kennt {n}()", False)
    print(f"\n\033[1m{OK} OK, {FAIL} FAIL\033[0m  (aelterer Stand - Rest uebersprungen)")
    sys.exit(1)

L.LEARNED_DIR = SAND / "learned"
L.LEARNED_DIR.mkdir(parents=True, exist_ok=True)
if not str(L.LEARNED_DIR).startswith(str(SAND)):
    print("\033[31mABBRUCH\033[0m: Sandkasten greift nicht - der Test wuerde in "
          "den echten Bestand schreiben.")
    sys.exit(2)

print("\033[1m1. Aufgaben-Kennung ist stabil\033[0m")
AUF = "Erstelle eine PowerPoint-Präsentation mit 6 Folien über die Vorteile von Prozessautomatisierung"
check("gleiche Aufgabe -> gleiche Kennung",
      L.task_kennung(AUF) == L.task_kennung(AUF))
check("Gross/Klein und Leerraum aendern nichts",
      L.task_kennung(AUF) == L.task_kennung("  erstelle eine POWERPOINT-Präsentation mit 6   Folien "
                                            "über die Vorteile von Prozessautomatisierung "))
check("andere Aufgabe -> andere Kennung",
      L.task_kennung(AUF) != L.task_kennung("Wie funktioniert der LDT-Import in Medistar?"))
check("Kennung ist kurz und dateinamenstauglich",
      L.task_kennung(AUF).isalnum() and len(L.task_kennung(AUF)) <= 12)

print("\n\033[1m2. bereits_gelernt: der gemeldete Fall\033[0m")
mon = L.LEARNED_DIR / "2026-09"
mon.mkdir(parents=True, exist_ok=True)
erste = mon / f"conv_1788500280_{L.task_kennung(AUF)}.md"
erste.write_text("# Gelernt: x\n\n- [A]: B\n", encoding="utf-8")

check("dieselbe Aufgabe gilt als schon gelernt",
      L.bereits_gelernt(AUF) is not None)
check("eine ANDERE Aufgabe nicht",
      L.bereits_gelernt("Wie funktioniert der LDT-Import in Medistar?") is None)
check("leere Aufgabe blockiert nichts",
      L.bereits_gelernt("") is None)

# Ausserhalb des Fensters -> wieder lernbar
alt_ts = time.time() - (L.wiederhol_fenster_tage() + 2) * 86400
os.utime(erste, (alt_ts, alt_ts))
check("ausserhalb des Zeitfensters wird wieder gelernt",
      L.bereits_gelernt(AUF) is None)
os.utime(erste, None)
check("frisch wieder innerhalb des Fensters", L.bereits_gelernt(AUF) is not None)

os.environ["JARVIS_LERN_FENSTER_TAGE"] = "0"
check("Fenster 0 schaltet die Dedup AUS (Notausgang)",
      L.wiederhol_fenster_tage() == 0 and L.bereits_gelernt(AUF) is None)
os.environ.pop("JARVIS_LERN_FENSTER_TAGE")
check("Fenster ist eine FUNKTION, keine eingefrorene Konstante",
      isinstance(L.wiederhol_fenster_tage, type(L.task_kennung)))

# Konsolidat darf nie treffen
kons = L.LEARNED_DIR / "konsolidiert"
kons.mkdir(exist_ok=True)
(kons / f"conv_9999_{L.task_kennung('nur konsolidat')}.md").write_text("- [A]: B\n", encoding="utf-8")
check("das Konsolidat blockiert kein Lernen",
      L.bereits_gelernt("nur konsolidat") is None)

print("\n\033[1m3. Selbstauskunft wird verworfen - an den ECHTEN Zeilen\033[0m")
# ⚠ DIE PFADREGEL LEITET AUS PROJECT_ROOT AB - und das ist auf DEV/ECHT
# "/opt/jarvis", im Arbeitsbaum aber ein anderer Pfad. Die gemessenen Zeilen
# stammen aus der DEV-Installation, also wird die Eigenschaft mit DEREN Pfad
# geprueft. Ohne diese Umstellung meldet der Waechter einen Fehler, den es auf
# dem Server nicht gibt.
_ECHT_ROOT = Path("/opt/jarvis")
_LOKAL_ROOT = L.PROJECT_ROOT
check("Positivkontrolle: mit dem EIGENEN Pfad greift die Regel",
      L._ohne_selbstbezug(f"- [X]: Die Datei liegt unter {_LOKAL_ROOT}/backend/x.py.", set()) == "")
L.PROJECT_ROOT = _ECHT_ROOT
check("Positivkontrolle: der DEV-Pfad ist jetzt der eigene",
      str(_ECHT_ROOT) in L._eigene_pfade())
WERKZEUGE = {"office_template_info", "office_create_powerpoint", "shell_execute"}
# ── Zeilen WOERTLICH aus dem DEV-Bestand ──────────────────────────────────
SELBST = [
    "- [Standard.pptx Vorlagenpfad]: Der Pfad /opt/jarvis/data/vorlagen/standard.pptx ist die feste Referenz.",
    "- [Layout-Parameter]: Das Tool office_create_powerpoint erwartet für das Layout-Feld ausschließlich die Kurznamen abschnitt oder bild.",
    "- [Browser-Addon-Pfade]: Die Jira-Browsererweiterung liegt in `/opt/jarvis/browser-addon/`.",
    "- [Test-Speicherung]: Automatisierte UI-Tests befinden sich unter `/opt/jarvis/tests/test_browser_addon.js`.",
]
BLEIBT = [
    "- [SOP Urlaubsplanung]: Genehmigte Urlaube werden im Outlook-Shared-Kalender \"Personalplanung\" angelegt.",
    "- [Nexus-SAP Medicare IPs]: 191.100.43.145 und 191.100.43.149 sind den Medicare-Umgebungen zugeordnet.",
    "- [Medicare SAP Version]: Deployments nutzen stabil Version 19.8.0.0.0.",
    "- [Confluence Medi Interfaces]: Dokument-ID 318456676 dokumentiert Datenbank-Hosts.",
    # ⚠ DIE ENGE REGEL IST ABSICHT: ein Kundenfakt mit /tmp darf NICHT fallen.
    "- [Medistar-Import]: Der Import legt seine Protokolle unter /tmp/medistar ab.",
]
for z in SELBST:
    check("verworfen: " + z[3:48],
          L._ohne_selbstbezug(z, WERKZEUGE) == "")
for z in BLEIBT:
    check("bleibt:    " + z[3:48],
          L._ohne_selbstbezug(z, WERKZEUGE) == z)

gem = "\n".join(SELBST + BLEIBT)
uebrig = L._ohne_selbstbezug(gem, WERKZEUGE)
check("gemischter Block: genau die Kundenfakten bleiben",
      uebrig.splitlines() == BLEIBT)
check("ohne Werkzeuge greift die Pfadregel weiterhin",
      L._ohne_selbstbezug(SELBST[0], set()) == "")
check("Werkzeugname nur mit Wortgrenze (kein Treffer in 'delegated')",
      L._ohne_selbstbezug("- [X]: Die Aufgabe wurde delegated und abgeschlossen.", {"delegate"})
      != "")
check("die eigenen Pfade werden aus PROJECT_ROOT ABGELEITET, nicht gepflegt",
      any(str(L.PROJECT_ROOT) == p for p in L._eigene_pfade()))
check("das Home des Dienstbenutzers zaehlt mit (/home/jarvis/pi.py im Bestand)",
      "/home/jarvis" in L._eigene_pfade())

print("\n\033[1m4. Der Lauf: kein LLM-Aufruf bei bekannter Aufgabe\033[0m")


class Prov:
    def __init__(self, antwort="- [Neu]: Ein Kundenfakt ueber Medistar mit genug Zeichen fuer die Substanzpruefung."):
        self.aufrufe = 0
        self.antwort = antwort

    async def generate_response(self, **kw):
        self.aufrufe += 1

        class P:
            text = self.antwort
        class R:
            parts = [P()]
        return R()


MSGS = [{"role": "tool", "tool": "office_template_info", "content": "Vorlage: standard.pptx"}]
geschrieben = []
L._save_and_index = lambda t, f: geschrieben.append((t, f))

os.environ.pop("JARVIS_LERN_FENSTER_TAGE", None)
p1 = Prov()
asyncio.run(L.learn_from_conversation("Ganz neue Frage zu Medistar", MSGS, p1, "m"))
check("neue Aufgabe: LLM wird gefragt", p1.aufrufe == 1)
check("neue Aufgabe: es wird gespeichert", len(geschrieben) == 1)

# Datei anlegen, wie es _save_and_index taete
(mon / f"conv_{int(time.time())}_{L.task_kennung('Ganz neue Frage zu Medistar')}.md").write_text(
    "- [A]: B\n", encoding="utf-8")
p2 = Prov()
asyncio.run(L.learn_from_conversation("Ganz neue Frage zu Medistar", MSGS, p2, "m"))
check("⚠ bekannte Aufgabe: GAR KEIN LLM-Aufruf (spart 68 % der Laeufe)", p2.aufrufe == 0)
check("bekannte Aufgabe: nichts gespeichert", len(geschrieben) == 1)

p3 = Prov(antwort="- [Vorlagenpfad]: Die Standardvorlage liegt unter /opt/jarvis/data/vorlagen/standard.pptx (16:9).")
asyncio.run(L.learn_from_conversation("Wieder etwas anderes zu Medistar", MSGS, p3, "m"))
check("⚠ reine Selbstauskunft wird NICHT gespeichert", len(geschrieben) == 1)

print("\n\033[1m5. Der Dateiname traegt die Kennung (kein Indexfile)\033[0m")
QUELLE = Q
check("Dateiname enthaelt task_kennung",
      'f"conv_{ts}_{task_kennung(task)}.md"' in QUELLE)
check("die Suche geht ueber den Dateibestand, nicht ueber ein Indexfile",
      'rglob(f"conv_*_{kennung}.md")' in QUELLE)

print("\n\033[1m6. Die Reihenfolge IST die Ersparnis\033[0m")
baum = ast.parse(QUELLE)
fn = next(n for n in ast.walk(baum)
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "learn_from_conversation")
namen = [n.func.id for n in ast.walk(fn)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
check("bereits_gelernt() steht VOR _extract_facts_llm()",
      "bereits_gelernt" in namen and "_extract_facts_llm" in namen
      and namen.index("bereits_gelernt") < namen.index("_extract_facts_llm"))
check("_ohne_selbstbezug() laeuft nach der Extraktion",
      "_ohne_selbstbezug" in namen)

print("\n\033[1m7. Der Extraktions-Prompt verbietet Selbstauskunft\033[0m")
check("Prompt nennt das Verbot ausdruecklich",
      "ueber DICH SELBST" in QUELLE and "System-Prompt" in QUELLE)
check("er begruendet es (steht schon im Prompt)",
      "kein neues Wissen" in QUELLE)

import shutil
shutil.rmtree(SAND, ignore_errors=True)
print(f"\n\033[1m{OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
