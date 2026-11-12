#!/usr/bin/env python3
"""Wissensgraph: gleicher Eingabetext = kein Modellaufruf, kein Nachlauf.

Anlass ECHT 2026-11-12: das Loesungsarchiv schrieb nachts 3.073 Dateien neu,
in den meisten nur Zaehler und Ticketliste. Der Graph las jede komplett neu
(~6.000 Modellaufrufe, 800/h am Deckel), und der Nachlauf pruefte danach jeden
betroffenen Begriff erneut, weil sich die mtime seiner Quellen geaendert hatte.

  1. ``kopf_entfernen``: Kopf ("Quelle/Vorkommen/Stand") und Ticketliste des
     Loesungsarchivs fallen weg – gemessen an Dateien, die der ERZEUGER
     (``loesungsarchiv.markdown``) baut, durch das echte Chunking. Zaehler und
     Ticketliste aendern den Eingabetext nicht, Problem/Loesung schon. Fremde
     Texte mit "## Tickets" bleiben unberuehrt; die Ticketliste geht nur weg,
     wenn danach NICHTS anderes mehr steht.
  2. ``eine_datei_bearbeiten``: neue mtime + gleicher Text → 'unveraendert',
     KEIN Modellaufruf, Quelle traegt die neue mtime, ``stand`` bleibt alt,
     Entitaeten bleiben, der Graph wird nicht als veraltet markiert. Neuer
     Text → Modellaufruf, ``stand`` = neue mtime. Neuaufbau mit "voll" →
     Modellaufruf trotz gleichem Text. Altbestand ohne ``text_sha`` → Aufruf.
  3. Nachlauf: ``inhalts_stand`` behaelt ``stand``, ``quellen_index`` zeigt die
     neue mtime; ein Widerspruchsbefund bleibt nach dem Bestaetigen gueltig.
  4. Abgleich: eine bestaetigte Quelle wird nicht erneut eingereiht; "voll"
     markiert den Warteschlangen-Eintrag.

    python3 tests/test_wissensgraph_unveraendert.py
"""
import asyncio
import json
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(name, cond, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


def section(t):
    print("\n" + t)


class _Cfg:
    profiles = []

    def get_setting(self, k, d=None):
        return d

    def __getattr__(self, n):
        return None


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
sys.modules["backend.config"] = _cfgmod

try:
    from backend import llm
    from backend import loesungsarchiv as la
    from backend import wissensgraph as wg
    from backend import wissensgraph_extraktion as wgx
    from backend.tools.knowledge import _chunk_text
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)

for name in ("eingabe_text", "text_sha", "eine_datei_bearbeiten", "abgleich"):
    if not callable(getattr(wgx, name, None)):
        print(f"ABBRUCH – wgx.{name} fehlt")
        sys.exit(2)
for name in ("quelle_bestaetigen", "inhalts_stand", "stand_von", "quellen_index"):
    if not callable(getattr(wg, name, None)):
        print(f"ABBRUCH – wg.{name} fehlt")
        sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="wg_unv_"))
wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)
R = str(wg.PROJECT_ROOT)


def eintrag(n, loesung="1. Treiber tauschen\n2. Dienst neu starten"):
    """Ein Archiv-Eintrag mit n Tickets – die Datei baut der ERZEUGER."""
    return {"titel": "PDFs erscheinen schwarz",
            "problem": "Symptom: Befund-PDF schwarz. Ursache: veralteter Druckertreiber.",
            "loesung": loesung, "schlagworte": ["PDF", "Druck"], "zaehler": n,
            "bereiche": ["PRJA", "PRJB"],
            "tickets": [{"key": f"PRJA-{100 + i}", "link": f"https://beispiel.de/browse/PRJA-{100 + i}",
                         "geloest": f"2024-03-{i % 28 + 1:02d}"} for i in range(n)]}


def eingabe(e):
    return wgx.eingabe_text(_chunk_text(la.markdown(e)))


# ── 1. Kopf und Ticketliste ─────────────────────────────────────────────────
section("1. kopf_entfernen am Loesungsarchiv")
md3 = la.markdown(eintrag(3))
check("Positivkontrolle: die Erzeugerdatei traegt Kopf und Ticketliste",
      "> Vorkommen: 3" in md3 and "## Tickets" in md3 and "PRJA-100" in md3)
e3, e400 = eingabe(eintrag(3)), eingabe(eintrag(400))
check("Positivkontrolle: 400 Tickets ergeben mehrere Chunks",
      len(_chunk_text(la.markdown(eintrag(400)))) > 1)
check("der Eingabetext enthaelt keinen Kopf mehr",
      "Vorkommen" not in e3 and "Lösungsarchiv" not in e3 and "Stand:" not in e3, e3[:200])
check("der Eingabetext enthaelt keine Ticketliste und keinen Link",
      "## Tickets" not in e400 and "PRJA-" not in e400 and "beispiel.de" not in e400, e400[-200:])
check("Titel, Problem, Loesung und Schlagworte bleiben stehen",
      all(x in e3 for x in ("PDFs erscheinen schwarz", "Druckertreiber", "Treiber tauschen", "Schlagworte")))
check("3 gegen 400 Tickets: derselbe Eingabetext und dieselbe Pruefsumme",
      e3 == e400 and wgx.text_sha(e3) == wgx.text_sha(e400))
e_neu = eingabe(eintrag(3, loesung="1. Treiber aktualisieren"))
check("geaenderte Loesung: anderer Eingabetext", e_neu != e3 and wgx.text_sha(e_neu) != wgx.text_sha(e3))
fremd = "# Notiz\n\nWir haben folgende Tickets.\n\n## Tickets\n\n- [PRJA-1](https://beispiel.de/x)\n"
check("ein fremdes Dokument mit '## Tickets' bleibt unberuehrt",
      wgx.kopf_entfernen(" ".join(fremd.split())) == " ".join(fremd.split()))
mit_rest = md3 + "\n## Nachtrag\n\nWichtiger Hinweis zum Druck.\n"
r = wgx.eingabe_text(_chunk_text(mit_rest))
check("steht nach der Ticketliste noch Inhalt, bleibt die Liste samt Inhalt stehen",
      "Wichtiger Hinweis" in r and "## Tickets" in r, r[-200:])
cf = ("Seite > Quelle: Confluence · Bereich (PRJA) · https://beispiel.de/x "
      "> Stand: Version 3, abgeglichen 01.02.2026 10:00 Inhalt der Seite")
check("der Confluence-Kopf wird weiter entfernt",
      wgx.kopf_entfernen(cf) == "Seite Inhalt der Seite", wgx.kopf_entfernen(cf))


# ── 2. Arbeiterschritt ──────────────────────────────────────────────────────
section("2. eine_datei_bearbeiten: gleicher Text kostet keinen Aufruf")


class FakeVS:
    def __init__(self):
        self.c, self.mt = {}, {}

    def get_indexed_files(self):
        return dict(self.mt)

    def chunks_fuer(self, p):
        return (list(self.c[p]), self.mt.get(p)) if p in self.c else ([], None)


class FakeK(types.ModuleType):
    def __init__(self, vs, folders):
        super().__init__("fake_knowledge")
        self.vs, self.folders = vs, folders
        self._reindex_lock = threading.Lock()

    def _get_vector_store(self):
        return self.vs

    def _get_folders(self):
        return self.folders

    def _nutzbare_ordner(self, folders, indexed, streng=True):
        return list(folders)

    def _verwaiste_dateien(self, current, indexed, alive):
        return []


class FakeProvider:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.n = 0

    async def generate_response(self, model, system_prompt, contents, tools=None,
                                reasoning_effort=None, temperature=None):
        self.n += 1
        text = self.antworten.pop(0) if self.antworten else "kaputt"
        return llm.LLMResponse(parts=[llm.LLMPart(text=text)], raw={}, usage={})


def kodieren(namen):
    import numpy as np
    return np.eye(len(namen), 8, dtype="float32") if namen else np.zeros((0, 8), "float32")


GUT = json.dumps({"entitaeten": [{"name": "Druckertreiber", "typ": "konzept", "beschreibung": "x"}],
                  "relationen": []})
ST = {**wgx.VORGABEN, "rate_min_abstand_s": 0, "rate_max_pro_stunde": 0, "gruppen": []}
D = "data/rag/x/archiv/abc_PDFs.md"
fk = FakeK(FakeVS(), [Path(R) / "data/rag/x"])
wgx._wissen = lambda: fk
ABS = wg.absolut(D)


def setze(e, mtime):
    fk.vs.c[ABS] = _chunk_text(la.markdown(e))
    fk.vs.mt[ABS] = mtime


def schritt(provider):
    e = dict(wg.warteschlange()).get(D)
    if e is None:
        return "KEIN EINTRAG"
    return asyncio.run(wgx.eine_datei_bearbeiten(D, e, ST, provider, "m", wgx.Kandidaten(kodieren=kodieren)))


setze(eintrag(3), 10.0)
wg.einreihen(D, 10.0)
p = FakeProvider([GUT])
r = schritt(p)
q = wg.quelle_lesen(D) or {}
check("Positivkontrolle: erste Extraktion ruft das Modell und legt die Quelle an",
      r == "ok" and p.n >= 1 and q.get("text_sha") == wgx.text_sha(eingabe(eintrag(3))), f"{r} n={p.n}")
check("eine frische Extraktion setzt stand = mtime", wg.stand_von(q) == 10.0 and q.get("stand") == 10.0, str(q.get("stand")))
zeitpunkt0 = q.get("zeitpunkt")

setze(eintrag(7), 20.0)                         # nur Zaehler und Ticketliste neu
wg.einreihen(D, 20.0)
wg.graph()                                      # Graph frisch ableiten ...
p = FakeProvider([GUT])
r = schritt(p)
q = wg.quelle_lesen(D) or {}
check("nur Zaehler/Ticketliste neu: 'unveraendert' und KEIN Modellaufruf", r == "unveraendert" and p.n == 0,
      f"{r} n={p.n}")
check("die Quelle traegt die neue mtime, der Inhaltsstand bleibt alt",
      q.get("mtime") == 20.0 and wg.stand_von(q) == 10.0, f"mtime={q.get('mtime')} stand={q.get('stand')}")
check("Entitaeten und Extraktionszeitpunkt bleiben stehen",
      [e.get("name") for e in q.get("entitaeten") or []] == ["Druckertreiber"] and q.get("zeitpunkt") == zeitpunkt0)
check("der Eintrag ist aus der Warteschlange", wg.warteschlange_laenge() == 0)
check("der Graph ist nach dem Bestaetigen NICHT als veraltet markiert", wg._graph_veraltet is False)
check("der Zaehler 'unveraendert' steht im Status",
      wgx._zustand["zaehler"].get("unveraendert", 0) >= 1, str(wgx._zustand["zaehler"]))

setze(eintrag(7, loesung="1. Treiber aktualisieren"), 30.0)
wg.einreihen(D, 30.0)
p = FakeProvider([GUT])
r = schritt(p)
q = wg.quelle_lesen(D) or {}
check("geaenderte Loesung: Modellaufruf, stand = neue mtime",
      r == "ok" and p.n >= 1 and wg.stand_von(q) == 30.0, f"{r} n={p.n} stand={q.get('stand')}")

wg.einreihen(D, 30.0, voll=True)
check("Positivkontrolle: 'voll' steht am Warteschlangen-Eintrag", dict(wg.warteschlange()).get(D, {}).get("voll") is True)
p = FakeProvider([GUT])
r = schritt(p)
check("Neuaufbau mit 'voll': Modellaufruf trotz gleichem Text", r == "ok" and p.n >= 1, f"{r} n={p.n}")

alt = wg.quelle_lesen(D)
alt.pop("text_sha", None)
alt.pop("stand", None)
wg._json_schreiben(wg._quell_datei(D), alt)
check("Altbestand ohne stand: stand_von faellt auf die mtime zurueck", wg.stand_von(wg.quelle_lesen(D)) == 30.0)
setze(eintrag(9, loesung="1. Treiber aktualisieren"), 40.0)
wg.einreihen(D, 40.0)
p = FakeProvider([GUT])
r = schritt(p)
check("Altbestand ohne text_sha: es wird extrahiert, nicht geraten", r == "ok" and p.n >= 1, f"{r} n={p.n}")


# ── 3. Nachlauf-Stand ───────────────────────────────────────────────────────
section("3. Nachlauf sieht den Inhaltsstand, nicht die mtime")
D2 = "data/rag/x/archiv/def_Zweite.md"
wg.quelle_schreiben(D2, 5.0, [{"name": "Druckertreiber", "typ": "konzept", "beschreibung": "y"}], [], "m",
                    {"text_sha": "0" * 16})
wg.widersprueche_schreiben({"geprueft": {}, "befunde": [
    {"id": "b1", "a": D, "b": D2, "mtime_a": 40.0, "mtime_b": 5.0, "begriff": "k:x"}]})
check("Positivkontrolle: der Befund gilt vor dem Bestaetigen", len(wg.widersprueche_gueltig()) == 1)
wg.quelle_bestaetigen(D2, 6.0)
check("quellen_index zeigt die neue mtime", wg.quellen_index().get(D2) == 6.0, str(wg.quellen_index().get(D2)))
check("inhalts_stand zeigt den alten Inhaltsstand", wg.inhalts_stand().get(D2) == 5.0, str(wg.inhalts_stand().get(D2)))
check("der Widerspruchsbefund bleibt nach dem Bestaetigen gueltig", len(wg.widersprueche_gueltig()) == 1)
check("auch die Ableitung des Graphen haelt die Widerspruchskante",
      any(k["art"] == wg.KANTE_WIDERSPRUCH for k in (wg._veraltet_markieren() or wg.graph())["kanten"]))
wg.quelle_schreiben(D2, 7.0, [{"name": "Druckertreiber", "typ": "konzept", "beschreibung": "y"}], [], "m", {})
check("eine echte Neu-Extraktion macht den Befund ungueltig", len(wg.widersprueche_gueltig()) == 0)


# ── 4. Abgleich ─────────────────────────────────────────────────────────────
section("4. Abgleich: bestaetigt heisst nicht wieder einreihen")
wg.warteschlange_leeren()
wg.quelle_bestaetigen(D, 50.0)
fk.vs.mt = {ABS: 50.0}
a = wgx.abgleich(gruppen=[])
check("die bestaetigte Quelle gilt als unveraendert", a["unveraendert"] == 1 and wg.warteschlange_laenge() == 0, str(a))
a = wgx.abgleich(gruppen=[], voll=True)
check("ein Vollaufbau reiht sie ein und markiert 'voll'",
      a["eingereiht"] == 1 and dict(wg.warteschlange()).get(D, {}).get("voll") is True, str(a))
wg.warteschlange_leeren()
# Die Datei WARTET schon (gleiche mtime), dann kommt der Vollaufbau: der
# vorhandene Eintrag muss "voll" bekommen, sonst wird sie still uebersprungen.
wg.einreihen(D, 50.0)
check("Positivkontrolle: wartender Eintrag ohne 'voll'", not dict(wg.warteschlange()).get(D, {}).get("voll"))
a = wgx.abgleich(gruppen=[], voll=True)
check("Vollaufbau ueber einen schon wartenden Eintrag markiert ihn 'voll'",
      dict(wg.warteschlange()).get(D, {}).get("voll") is True and wg.warteschlange_laenge() == 1,
      str(dict(wg.warteschlange()).get(D)))
wg.warteschlange_leeren()

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
