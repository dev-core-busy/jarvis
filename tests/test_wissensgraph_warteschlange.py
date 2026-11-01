#!/usr/bin/env python3
"""Wissensgraph: Warteschlange, Wiederaufnahme, Fehlversuche, Drossel, Arbeiterschritt.

  1. Die Schlange uebersteht einen Neustart (Caches verworfen, von Platte geladen),
     in Reihenfolge des Einreihens.
  2. Drei Fehlversuche → Negativ-Cache (mit mtime: eine geaenderte Datei kommt
     wieder in Frage); der Abgleich ueberspringt bekannt Unlesbares.
  3. ``erledigt`` nimmt einen NEUER eingereihten Stand nicht mit heraus.
  4. Drossel mit gestellter Uhr: Mindestabstand UND Obergrenze je Stunde.
  5. ``eine_datei_bearbeiten`` von Anfang bis Ende mit echter Antwortform:
     Erfolg, Fehlschlag bis Negativ-Cache, Datei inzwischen geaendert,
     Index wird gerade neu aufgebaut, ausserhalb des Umfangs.
  6. ``abbrechen`` leert die Schlange.

    python3 tests/test_wissensgraph_warteschlange.py
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
    from backend import wissensgraph as wg
    from backend import wissensgraph_extraktion as wgx
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="wg_queue_"))
wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)
R = str(wg.PROJECT_ROOT)

# ── 1. Wiederaufnahme ───────────────────────────────────────────────────────
section("1. Die Schlange uebersteht einen Neustart")
for i, n in enumerate(("c.md", "a.md", "b.md")):
    wg.einreihen(f"data/rag/x/{n}", float(i), sichern=False)
check("Positivkontrolle: drei im Speicher", wg.warteschlange_laenge() == 3)
wg.warteschlange_sichern()
wg._zuruecksetzen_fuer_test()           # "Neustart": Speicher weg, nur die Platte zaehlt
check("nach dem Neustart: alle drei da, in Reihenfolge des Einreihens",
      [m for m, _ in wg.warteschlange()] == ["data/rag/x/c.md", "data/rag/x/a.md", "data/rag/x/b.md"],
      str([m for m, _ in wg.warteschlange()]))
wg.einreihen("data/rag/x/a.md", 1.0)
check("gleiche mtime erneut einreihen: kein Duplikat, Platz bleibt",
      [m for m, _ in wg.warteschlange()][1] == "data/rag/x/a.md" if wg.warteschlange_laenge() == 3 else False)
wg.warteschlange_leeren()

# ── 2. Fehlversuche → Negativ-Cache ─────────────────────────────────────────
section("2. Drei Fehlversuche, dann Negativ-Cache")
M = "data/rag/x/kaputt.pdf"
wg.einreihen(M, 7.0)
erg = [wg.fehlversuch(M, 7.0, f"Fehler {i}", wgx.MAX_VERSUCHE) for i in range(wgx.MAX_VERSUCHE)]
check("aufgegeben erst beim letzten Versuch", erg == [False] * (wgx.MAX_VERSUCHE - 1) + [True], str(erg))
check("danach nicht mehr in der Schlange", wg.warteschlange_laenge() == 0)
check("Negativ-Cache trifft dieselbe mtime", wg.unlesbar_trifft(M, 7.0))
check("eine GEAENDERTE Datei (neue mtime) trifft ihn nicht", not wg.unlesbar_trifft(M, 8.0))
wg._zuruecksetzen_fuer_test()
check("der Negativ-Cache uebersteht einen Neustart", wg.unlesbar_trifft(M, 7.0))


class FakeVS:
    def __init__(self, chunks_je_pfad, mtime_je_pfad=None):
        self.c = chunks_je_pfad
        self.mt = mtime_je_pfad or {}

    def get_indexed_files(self):
        return {p: self.mt.get(p, 7.0) for p in self.c}

    def chunks_fuer(self, p):
        return (list(self.c[p]), self.mt.get(p, 7.0)) if p in self.c else ([], None)


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


fk = FakeK(FakeVS({wg.absolut(M): ["text"]}), [Path(R) / "data/rag/x"])
wgx._wissen = lambda: fk
a = wgx.abgleich(gruppen=[])
check("der Abgleich ueberspringt bekannt Unlesbares (unveraendert)",
      a["bekannt_unlesbar"] == 1 and wg.warteschlange_laenge() == 0, str(a))
a = wgx.abgleich(gruppen=[], voll=True)
check("ein Vollaufbau versucht es trotzdem erneut", a["eingereiht"] == 1, str(a))
wg.warteschlange_leeren()

# ── 3. erledigt und neuer Stand ─────────────────────────────────────────────
section("3. erledigt nimmt einen neueren Stand nicht mit")
wg.einreihen("data/rag/x/n.md", 1.0)
wg.einreihen("data/rag/x/n.md", 2.0)        # Datei hat sich waehrend der Arbeit geaendert
wg.erledigt("data/rag/x/n.md", 1.0)
check("der neuere Eintrag bleibt", [e["mtime"] for _, e in wg.warteschlange()] == [2.0])
wg.erledigt("data/rag/x/n.md", 2.0)
check("mit passender mtime wird er ausgetragen", wg.warteschlange_laenge() == 0)

# ── 4. Drossel ──────────────────────────────────────────────────────────────
section("4. Drossel (gestellte Uhr)")
uhr = {"t": 1000.0}
geschlafen = []


async def schlafen(s):
    geschlafen.append(s)
    uhr["t"] += s

dr = wgx.Drossel(uhr=lambda: uhr["t"], schlafen=schlafen)


async def zeitpunkte(n, abstand, max_h):
    raus = []
    for _ in range(n):
        await dr.warten(abstand, max_h)
        raus.append(uhr["t"])
    return raus

t = asyncio.run(zeitpunkte(3, 2.0, 0))
check("Mindestabstand 2 s: Aufrufe 2 s auseinander", [round(b - a, 3) for a, b in zip(t, t[1:])] == [2.0, 2.0],
      str(t))
uhr["t"] = 50000.0
dr = wgx.Drossel(uhr=lambda: uhr["t"], schlafen=schlafen)
t = asyncio.run(zeitpunkte(4, 0.0, 3))
check("Obergrenze 3 je Stunde: der vierte wartet bis eine Stunde nach dem ersten",
      round(t[3] - t[0], 3) == 3600.0, str([round(x - t[0], 1) for x in t]))
check("die Drossel schlaeft in Haeppchen (bleibt abbrechbar)", max(geschlafen) <= 60.0, str(max(geschlafen)))

# ── 5. Arbeiterschritt ──────────────────────────────────────────────────────
section("5. eine_datei_bearbeiten von Anfang bis Ende")


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


GUT = json.dumps({"entitaeten": [{"name": "Contoso", "typ": "organisation", "beschreibung": "x"}],
                  "relationen": []})
ST = {**wgx.VORGABEN, "rate_min_abstand_s": 0, "rate_max_pro_stunde": 0, "gruppen": []}
D = "data/rag/x/doc.md"


async def schritt(provider, eintrag_mtime=7.0):
    e = dict(wg.warteschlange()).get(D) or {"mtime": eintrag_mtime}
    return await wgx.eine_datei_bearbeiten(D, e, ST, provider, "m", wgx.Kandidaten(kodieren=kodieren))

fk = FakeK(FakeVS({wg.absolut(D): ["eins zwei drei"]}), [Path(R) / "data/rag/x"])
wgx._wissen = lambda: fk
wg.einreihen(D, 7.0)
r = asyncio.run(schritt(FakeProvider([GUT])))
q = wg.quelle_lesen(D)
check("Erfolg: 'ok', Quelle geschrieben, Eintrag ausgetragen",
      r == "ok" and q is not None and wg.warteschlange_laenge() == 0, f"{r} {q is not None}")
check("die Quelle traegt die mtime des Index und die Herkunft",
      q is not None and q["mtime"] == 7.0 and q["pfad"] == D and q["bloecke"] == 1)

wg.einreihen(D, 8.0)
fk.vs.mt[wg.absolut(D)] = 8.0
for i in range(wgx.MAX_VERSUCHE):
    r = asyncio.run(schritt(FakeProvider(["kaputt", "kaputt"])))
check("Fehlschlag: 'fehler', nach MAX_VERSUCHE im Negativ-Cache",
      r == "fehler" and wg.unlesbar_trifft(D, 8.0) and wg.warteschlange_laenge() == 0,
      f"{r} {wg.unlesbar_trifft(D, 8.0)} {wg.warteschlange_laenge()}")
check("die alte, gueltige Quelle bleibt beim Fehlschlag stehen",
      wg.quelle_lesen(D) is not None and wg.quelle_lesen(D)["mtime"] == 7.0)

wg.einreihen(D, 9.0)
fk.vs.mt[wg.absolut(D)] = 10.0                 # Index ist schon weiter
p = FakeProvider([GUT])
r = asyncio.run(schritt(p))
check("Datei inzwischen geaendert: 'spaeter', neu eingereiht mit dem neuen Stand, kein Aufruf",
      r == "spaeter" and [e["mtime"] for _, e in wg.warteschlange()] == [10.0] and p.n == 0,
      f"{r} {wg.warteschlange()} {p.n}")
wg.warteschlange_leeren()

wg.einreihen("data/rag/x/fehlt.md", 1.0)
fk._reindex_lock.acquire()
e = dict(wg.warteschlange())["data/rag/x/fehlt.md"]
r = asyncio.run(wgx.eine_datei_bearbeiten("data/rag/x/fehlt.md", e, ST, FakeProvider([]), "m",
                                          wgx.Kandidaten(kodieren=kodieren)))
fk._reindex_lock.release()
check("nicht im Index WAEHREND eines Neu-Indizierens: 'spaeter', Eintrag bleibt",
      r == "spaeter" and wg.warteschlange_laenge() == 1, f"{r} {wg.warteschlange_laenge()}")
r = asyncio.run(wgx.eine_datei_bearbeiten("data/rag/x/fehlt.md", e, ST, FakeProvider([]), "m",
                                          wgx.Kandidaten(kodieren=kodieren)))
check("nicht im Index, kein Neuaufbau: 'uebersprungen', ausgetragen",
      r == "uebersprungen" and wg.warteschlange_laenge() == 0, f"{r} {wg.warteschlange_laenge()}")

wg.einreihen(D, 11.0)
fk.vs.mt[wg.absolut(D)] = 11.0
p = FakeProvider([GUT])
st_gruppe = {**ST, "gruppen": ["gibt-es-nicht"]}


async def schritt_gruppe():
    e = dict(wg.warteschlange())[D]
    import backend.knowledge_groups as kg
    alt = kg.filter_paths_by_groups
    kg.filter_paths_by_groups = lambda pfade, gids: []
    try:
        return await wgx.eine_datei_bearbeiten(D, e, st_gruppe, p, "m", wgx.Kandidaten(kodieren=kodieren))
    finally:
        kg.filter_paths_by_groups = alt
r = asyncio.run(schritt_gruppe())
check("ausserhalb des Umfangs: 'uebersprungen', kein Modellaufruf", r == "uebersprungen" and p.n == 0,
      f"{r} {p.n}")

# ── 6. abbrechen ────────────────────────────────────────────────────────────
section("6. abbrechen")
for i in range(3):
    wg.einreihen(f"data/rag/x/z{i}.md", 1.0)
erg = wgx.abbrechen()
check("abbrechen leert die Schlange und nennt die Zahl", erg == {"ok": True, "verworfen": 3}
      and wg.warteschlange_laenge() == 0, str(erg))
wgx._abbruch = False

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
