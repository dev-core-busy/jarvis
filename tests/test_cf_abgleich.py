#!/usr/bin/env python3
"""Waechter fuer den Confluence-Abgleich (Vorgabe 2026-09-27).

GEMESSEN WIRD DIE WIRKUNG, NICHT DAS VORKOMMEN: ``backend/confluence_abgleich``
laeuft WIRKLICH – gegen eine Confluence-Attrappe mit der ECHTEN Signatur und
Antwortform von ``ConfluenceClient`` (``pages_in_space(key, limit,
with_parent=, with_version=)``, ``get_page(id, None, None)`` mit
``body.storage.value``/``version.number``, ``space_homepage(key)``), in einem
Sandkasten mit echten Dateien. Ob eine geloeschte Seite verschwindet oder ein
Netzfehler den Bestand stehen laesst, kann eine Quelltext-Pruefung nicht
beantworten.

⚠ SANDKASTEN MIT EXIT 2. Wissensordner, Stand-Datei und Einbindungs-Ablage
liegen in einem Wegwerf-Verzeichnis; zeigt einer der Pfade heraus, bricht der
Lauf ab („konnte nicht laufen" ist nicht „bestanden"). ``backend.config``,
``knowledge_groups``, ``web_extractor`` und ``tools.knowledge`` sind Attrappen
in ``sys.modules`` – der echte Import schreibt die Live-``settings.json``.
"""
from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0
def section(t): print(f"\n\033[1m{t}\033[0m")
def check(desc, cond, info=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  \033[32m✓\033[0m {desc}")
    else:
        FAIL += 1; print(f"  \033[31m✗\033[0m {desc}" + (f" – {info}" if info else ""))

def sicher(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


# ════════════════════════════════════════════════════════════════════════════
section("0. Sandkasten und Attrappen")
SAND = Path(tempfile.mkdtemp(prefix="cfa-test-"))
ORDNER_A = SAND / "rag" / "technik"
ORDNER_B = SAND / "rag" / "vertrieb"
ORDNER_A.mkdir(parents=True); ORDNER_B.mkdir(parents=True)

cfgmod = types.ModuleType("backend.config")
class _Cfg:
    def get_setting(self, k, d=None): return d
    def save_setting(self, k, v): pass
    def get_skill_states(self): return {}
cfgmod.config = _Cfg()
sys.modules["backend.config"] = cfgmod

ZUORDNUNG: dict = {}
kg = types.ModuleType("backend.knowledge_groups")
def _set_assignment(rel, ids):
    ids = [g for g in (ids or []) if g]
    if ids:
        ZUORDNUNG[str(rel)] = list(ids)
    else:
        ZUORDNUNG.pop(str(rel), None)
    return ids
kg.set_assignment = _set_assignment
kg.list_groups = lambda *a, **k: {"groups": []}
sys.modules["backend.knowledge_groups"] = kg

we = types.ModuleType("backend.web_extractor")
def _target(groups):
    return ORDNER_B if (groups and groups[0] == "vertrieb") else ORDNER_A
we._target_dir_for_groups = _target
sys.modules["backend.web_extractor"] = we

tools = types.ModuleType("backend.tools"); tools.__path__ = []
tk = types.ModuleType("backend.tools.knowledge"); tk.PROJECT_ROOT = SAND
sys.modules["backend.tools"] = tools
sys.modules["backend.tools.knowledge"] = tk

NOTAUS = {"an": False}
ra = types.ModuleType("backend.rag_autoindex")
ra.abgeschaltet = lambda: NOTAUS["an"]
sys.modules["backend.rag_autoindex"] = ra

import backend.confluence_bindung as cfb  # noqa: E402
import backend.confluence_abgleich as cfa  # noqa: E402

ECHT_B, ECHT_A = cfb._pfad(), cfa._pfad()
ECHT_B_VOR = ECHT_B.read_bytes() if ECHT_B.is_file() else None
ECHT_A_VOR = ECHT_A.read_bytes() if ECHT_A.is_file() else None
cfb._pfad = lambda: SAND / "confluence_bindung.json"      # type: ignore[assignment]
cfa._pfad = lambda: SAND / "confluence_abgleich.json"     # type: ignore[assignment]
for nm, p in [("Einbindung", cfb._pfad()), ("Stand", cfa._pfad()),
              ("Ziel", _target(["technik"]))]:
    if SAND not in Path(p).parents:
        print(f"  \033[31m✗\033[0m Sandkasten greift NICHT fuer {nm} ({p}) – Abbruch")
        sys.exit(2)
check("alle Pfade zeigen in den Sandkasten", True)


class ConfluenceError(Exception):
    def __init__(self, status, msg=""):
        super().__init__(msg); self.status = status


class Attrappe:
    """Bildet ``ConfluenceClient`` nach: gleiche Signaturen, gleiche Antwortform."""

    def __init__(self):
        # key -> {id: {title, parent, version, body}}
        self.raeume: dict = {}
        self.start: dict = {}
        self.weg: set = set()          # Bereiche, deren Liste scheitert
        self.page_rufe: list = []
        self.listen_rufe: list = []
        self.label_rufe: list = []     # je Listenabruf: wurden Labels verlangt?
        self.ohne_labels: set = set()  # Bereiche, deren Antwort KEINE metadata traegt

    def seite(self, key, pid, titel, parent="", version=1, body=None, labels=None):
        self.raeume.setdefault(key, {})[pid] = {
            "title": titel, "parent": parent, "version": version,
            "labels": list(labels or []),
            "body": body if body is not None else f"<p>Inhalt {titel} v{version}</p>"}

    def pages_in_space(self, space, limit=500, with_parent=False, with_version=False,
                       with_labels=False):
        self.listen_rufe.append(space)
        self.label_rufe.append(with_labels)
        if space in self.weg:
            raise ConfluenceError(503, "Wartung")
        aus = []
        for pid, s in self.raeume.get(space, {}).items():
            it = {"id": pid, "title": s["title"], "link": f"https://cf/{pid}"}
            if with_parent:
                it["parent"] = s["parent"]
            if with_version:
                it["version"] = s["version"]
            if with_labels:
                # Wie der echte Client: fehlt metadata.labels, steht None da.
                it["labels"] = None if space in self.ohne_labels else [x.lower() for x in s["labels"]]
            aus.append(it)
        return aus[:limit]

    def space_homepage(self, space):
        return self.start.get(space, "")

    def get_page(self, page_id=None, title=None, space=None):
        self.page_rufe.append(page_id)
        for key, r in self.raeume.items():
            if page_id in r:
                s = r[page_id]
                return {"id": page_id, "title": s["title"],
                        "version": {"number": s["version"]},
                        "body": {"storage": {"value": s["body"]}}}
        raise ConfluenceError(404, "weg")


def lauf(c, aktiv=(True, "")):
    c.page_rufe.clear(); c.listen_rufe.clear(); c.label_rufe.clear()
    return cfa.lauf(client=c, aktiv=aktiv)

def dateien():
    return sorted(str(p.relative_to(SAND)) for p in (SAND / "rag").rglob("*.md"))

def stand():
    return cfa._stand_laden()


# ════════════════════════════════════════════════════════════════════════════
section("1. Aufloesung einer Auswahl (rein rechnerisch)")
LISTE = [{"id": "1", "parent": ""}, {"id": "2", "parent": "1"}, {"id": "3", "parent": "2"},
         {"id": "4", "parent": "1"}, {"id": "9", "parent": ""}]
S = cfa.seiten_der_auswahl
check("ganz = alle Seiten des Bereichs",
      S({"ganz": True}, LISTE) == {"1", "2", "3", "4", "9"})
check("einzelne Seiten zaehlen nur selbst",
      S({"seiten": ["2"]}, LISTE) == {"2"})
check("⚠ ein Zweig nimmt ALLES darunter mit (auch Enkel)",
      S({"seiten": ["1"], "zweige": ["1"]}, LISTE) == {"1", "2", "3", "4"})
check("⚠ eine Kennung, die es im Bereich nicht gibt, faellt heraus (kein Schmuggel)",
      S({"seiten": ["2", "777"], "zweige": ["888"]}, LISTE) == {"2"})
check("start = Startseite des Bereichs",
      S({"start": True}, LISTE, "9") == {"9"})
check("start ohne bekannte Startseite liefert nichts (kein Raten)",
      S({"start": True}, LISTE, "") == set())
zyklus = [{"id": "a", "parent": "b"}, {"id": "b", "parent": "a"}]
check("ein Zyklus in den Elternangaben haengt nicht",
      isinstance(sicher(S, {"seiten": ["a"], "zweige": ["a"]}, zyklus), set))


# ════════════════════════════════════════════════════════════════════════════
section("2. Erster Lauf: Seiten werden Dateien, mit Zuordnung")
C = Attrappe()
C.seite("CTDP", "100", "Handbuch")
C.seite("CTDP", "101", "Kapitel A", parent="100")
C.seite("CTDP", "102", "Kapitel B", parent="100")
C.seite("CTDP", "200", "Sonstiges")
C.seite("OPS", "300", "Betrieb Start")
C.seite("OPS", "301", "Betrieb Detail", parent="300")
C.start["OPS"] = "300"

e1 = cfb.hinzufuegen([{"key": "CTDP", "seiten": ["100"], "zweige": ["100"]},
                      {"key": "OPS", "start": True}], "tester", ["technik"])
check("(Positivkontrolle) Eintrag angelegt", isinstance(e1, dict), str(e1))

r = lauf(C)
check("Lauf meldet aktiv und einen Grund", r.get("aktiv") is True and bool(r.get("grund")), str(r))
check("vier Seiten neu (Zweig 100 = 100,101,102; OPS-Startseite 300)", r.get("neu") == 4, str(r))
check("Seite AUSSERHALB der Auswahl wird nicht geholt", "200" not in C.page_rufe, str(C.page_rufe))
check("Unterseite der Startseite ohne Zweig wird nicht geholt", "301" not in C.page_rufe)
fs = dateien()
check("vier Dateien liegen im Wissensordner", len(fs) == 4, str(fs))
check("Ablage unter <ordner>/confluence/<BEREICH>/",
      all("/confluence/" in f for f in fs) and any("/confluence/CTDP/" in f for f in fs), str(fs))
inh = next(((SAND / f).read_text(encoding="utf-8") for f in fs if "101_" in f), "")
check("⚠ der Seitentext steht 1:1 in der Datei (keine KI, kein Entwurf)",
      "Inhalt Kapitel A v1" in inh, inh[:200])
check("die Datei nennt ihre Quelle", "Quelle: Confluence" in inh and "CTDP" in inh)
check("jede Datei traegt die Wissensgruppe des Eintrags",
      len(ZUORDNUNG) == 4 and all(v == ["technik"] for v in ZUORDNUNG.values()), str(ZUORDNUNG))
st = stand()
check("der Stand fuehrt je Seite Version und Datei",
      st["seiten"].get("101", {}).get("v") == 1 and st["seiten"]["101"].get("datei"), str(st["seiten"].get("101")))
check("der Stand fuehrt je Eintrag das Ergebnis",
      (st["eintraege"].get(e1["id"]) or {}).get("seiten") == 4, str(st["eintraege"]))
check("Stand-Datei ist 0640", oct(cfa._pfad().stat().st_mode & 0o777) == "0o640")
check("eintrag_staende() liefert das Ergebnis fuer die Liste",
      (cfa.eintrag_staende().get(e1["id"]) or {}).get("seiten") == 4)


# ════════════════════════════════════════════════════════════════════════════
section("3. Nichts geaendert: kein Inhaltsabruf, nichts geschrieben")
mt = {f: (SAND / f).stat().st_mtime_ns for f in dateien()}
r = lauf(C)
check("⚠ kein einziger Inhaltsabruf", C.page_rufe == [], str(C.page_rufe))
check("aber die Seitenlisten wurden gelesen (sonst waere nichts erkennbar)",
      sorted(set(C.listen_rufe)) == ["CTDP", "OPS"], str(C.listen_rufe))
check("Grund: nichts geaendert", r.get("grund") == "nichts geaendert", str(r))
check("keine Datei neu geschrieben (mtime gleich)",
      all((SAND / f).stat().st_mtime_ns == m for f, m in mt.items()))


# ════════════════════════════════════════════════════════════════════════════
section("4. Aenderung, neue Unterseite, Loeschung")
C.seite("CTDP", "101", "Kapitel A", parent="100", version=2)
C.seite("CTDP", "103", "Kapitel C (neu)", parent="102")     # Enkel im Zweig
C.seite("OPS", "302", "Betrieb neu", parent="300")          # KEIN Zweig bei OPS
del C.raeume["CTDP"]["102"]                                 # in Confluence geloescht
C.raeume["CTDP"]["103"]["parent"] = "100"                   # (Elternseite ist weg)
r = lauf(C)
check("geaenderte Seite wird neu geholt", "101" in C.page_rufe, str(C.page_rufe))
inh = next(((SAND / f).read_text(encoding="utf-8") for f in dateien() if "101_" in f), "")
check("und ihr neuer Stand steht in der Datei", "v2" in inh, inh[:120])
check("⚠ neue Unterseite im KOMPLETTEN Zweig kommt automatisch mit",
      any("103_" in f for f in dateien()), str(dateien()))
check("⚠ neue Unterseite OHNE Zweig kommt NICHT mit",
      not any("302_" in f for f in dateien()))
check("⚠ in Confluence geloeschte Seite verschwindet aus dem Wissen",
      not any("102_" in f for f in dateien()), str(dateien()))
check("und ihre Zuordnung ebenfalls", not any("102_" in k for k in ZUORDNUNG))
check("die Zaehlung stimmt (1 neu, 1 geaendert, 1 entfernt)",
      (r.get("neu"), r.get("geaendert"), r.get("entfernt")) == (1, 1, 1), str(r))


# ════════════════════════════════════════════════════════════════════════════
section("5. ⚠ Ein fehlgeschlagener Abruf loescht NICHTS")
vorher = dateien()
C.weg.add("CTDP")
r = lauf(C)
check("(Positivkontrolle) der Abruf ist wirklich gescheitert", "CTDP" in C.listen_rufe and r.get("fehler", 0) >= 1, str(r))
check("⚠ alle Dateien des nicht erreichbaren Bereichs bleiben liegen",
      dateien() == vorher, f"{vorher} -> {dateien()}")
check("der Eintrag nennt den Fehler",
      "nicht erreichbar" in ((stand()["eintraege"].get(e1["id"]) or {}).get("fehler") or ""))
st = stand()
check("der Stand vergisst die Seiten nicht", "101" in st["seiten"] and "100" in st["seiten"])
C.weg.clear()
r = lauf(C)
check("nach der Wartung laeuft es ohne Neuabruf weiter", C.page_rufe == [] and dateien() == vorher, str(C.page_rufe))

# ⚠ Code-Review 2026-10-07: Confluence antwortet auf einen Bereich ohne
# Leserecht mit 200 und LEERER Liste – kein Fehler. Vorher galten damit alle
# importierten Seiten als "nicht mehr gewollt" und wurden geloescht.
section("5b. Leere Seitenliste bei vorhandenem Bestand = Fehlschlag, nichts geloescht")
_gesichert = {k: dict(v) for k, v in C.raeume.items()}
_bestand = {k: v for k, v in stand()["seiten"].items()}
_raeume_mit_bestand = sorted({v.get("space") for v in _bestand.values()})
check("Positivkontrolle: es gibt importierten Bestand (%s)" % _raeume_mit_bestand,
      bool(_bestand) and bool(vorher))
for _k in _raeume_mit_bestand:
    C.raeume[_k] = {}                 # Rechte entzogen: Liste leer, kein Fehler
r = lauf(C)
check("⚠ kein einziges Wissensdokument geloescht", dateien() == vorher, str(dateien()))
check("… nichts als entfernt gezaehlt", r.get("entfernt") == 0, str(r))
check("… der Stand behaelt alle Seiten", set(stand()["seiten"]) == set(_bestand))
check("… und der Lauf meldet einen Fehler mit Grund",
      r.get("fehler", 0) >= 1 and any("keine Seiten" in ((e or {}).get("fehler") or "")
                                      for e in stand()["eintraege"].values()), str(r))
C.raeume.clear()
C.raeume.update(_gesichert)
r = lauf(C)
check("danach (Rechte zurueck) wieder ohne Fehler und ohne Verlust",
      dateien() == vorher and r.get("entfernt") == 0, str(r))

section("5c. Liste an der Obergrenze = unvollstaendig, nichts geloescht")
# Code-Review 2026-10-07: was hinter MAX_SEITEN_JE_BEREICH liegt, ist nicht
# "nicht mehr gewollt", sondern nicht gelesen.
_max_vorher = cfa.MAX_SEITEN_JE_BEREICH
_groesster = max(_raeume_mit_bestand, key=lambda k: len(C.raeume.get(k, {})))
_n = len(C.raeume.get(_groesster, {}))
check("Positivkontrolle: ein Bereich mit mehr als einer Seite (%s: %d)" % (_groesster, _n), _n >= 2)
cfa.MAX_SEITEN_JE_BEREICH = _n - 1     # die Attrappe kappt wie der echte Client an `limit`
r = lauf(C)
cfa.MAX_SEITEN_JE_BEREICH = _max_vorher
check("⚠ gekappte Liste: kein Wissensdokument geloescht", dateien() == vorher, str(dateien()))
check("… nichts als entfernt gezaehlt, Fehler mit Grund",
      r.get("entfernt") == 0 and r.get("fehler", 0) >= 1
      and any("nicht vollständig" in ((e or {}).get("fehler") or "") for e in stand()["eintraege"].values()),
      str(r))
r = lauf(C)
check("Positivkontrolle: mit voller Liste wieder ohne Fehler", r.get("fehler", 0) == 0
      and dateien() == vorher, str(r))


# ════════════════════════════════════════════════════════════════════════════
section("6. Skill aus / Notaus = Pause, nicht Loeschen")
r = lauf(C, aktiv=(False, "Confluence-Skill ist nicht aktiv"))
check("Skill aus: kein Abruf", C.listen_rufe == [] and C.page_rufe == [])
check("Skill aus: nichts geloescht", dateien() == vorher)
check("Skill aus: Grund genannt, aktiv=False",
      r.get("aktiv") is False and "nicht aktiv" in r.get("grund", ""), str(r))
NOTAUS["an"] = True
r = lauf(C)
check("Notaus: kein Abruf", C.listen_rufe == [], str(C.listen_rufe))
NOTAUS["an"] = False


# ════════════════════════════════════════════════════════════════════════════
section("7. Bearbeiten und Loeschen des Eintrags wirken beim naechsten Lauf")
# OPS abwaehlen, CTDP komplett (ganz) – neue Seite 200 muss kommen, 300 gehen.
sicher(cfb.aendern, e1["id"], [{"key": "CTDP", "start": True, "ganz": True}], "tester", ["technik"])
r = lauf(C)
fs = dateien()
check("⚠ ganzer Bereich: auch die bisher nicht gewaehlte Seite 200 kommt", any("200_" in f for f in fs), str(fs))
check("⚠ abgewaehlter Bereich OPS verschwindet aus dem Wissen", not any("/OPS/" in f for f in fs), str(fs))
check("der leer gewordene Bereichsordner ist abgeraeumt",
      not (ORDNER_A / "confluence" / "OPS").exists())

# Zweiter Eintrag mit anderer Gruppe fuer DIESELBE Seite: Gruppen vereinigen, EINE Datei.
e2 = cfb.hinzufuegen([{"key": "CTDP", "seiten": ["200"]}], "tester", ["vertrieb"])
r = lauf(C)
treffer = [k for k in ZUORDNUNG if "200_" in k]
check("dieselbe Seite in zwei Eintraegen ergibt EINE Datei", len(treffer) == 1, str(treffer))
check("⚠ mit den Gruppen BEIDER Eintraege",
      len(treffer) == 1 and sorted(ZUORDNUNG[treffer[0]]) == ["technik", "vertrieb"],
      str({k: ZUORDNUNG[k] for k in treffer}))

cfb.entfernen(e1["id"])
r = lauf(C)
fs = dateien()
check("Eintrag geloescht: seine Seiten verschwinden", not any("101_" in f for f in fs), str(fs))
check("⚠ aber was ein ANDERER Eintrag abdeckt, bleibt", any("200_" in f for f in fs), str(fs))
check("und traegt nur noch dessen Gruppe",
      [v for k, v in ZUORDNUNG.items() if "200_" in k] == [["vertrieb"]], str(ZUORDNUNG))
cfb.entfernen(e2["id"])
r = lauf(C)
check("alle Eintraege geloescht: das Confluence-Wissen ist weg", dateien() == [], str(dateien()))
check("Grund ohne Eintraege: keine Einbindung", r.get("grund") in ("keine Einbindung", "1 entfernt"), str(r))


# ════════════════════════════════════════════════════════════════════════════
section("8. Deckel je Takt und Altbestand")
for i in range(cfa.MAX_ABRUFE_JE_LAUF + 7):
    C.seite("BIG", str(5000 + i), f"Seite {i}")
e3 = cfb.hinzufuegen([{"key": "BIG", "start": True, "ganz": True}], "tester", ["technik"])
r = lauf(C)
check(f"hoechstens {cfa.MAX_ABRUFE_JE_LAUF} Inhaltsabrufe je Takt",
      len(C.page_rufe) == cfa.MAX_ABRUFE_JE_LAUF, str(len(C.page_rufe)))
check("der Rest wird als offen gemeldet", r.get("offen") == 7, str(r))
check("und steht beim Eintrag", (stand()["eintraege"].get(e3["id"]) or {}).get("offen") == 7)
r = lauf(C)
check("der naechste Takt holt den Rest", len(C.page_rufe) == 7 and r.get("offen") == 0, str(r))
cfb.entfernen(e3["id"]); lauf(C)

# Altbestand ohne Gruppen: wird NICHT abgeglichen und nicht geraten.
import json  # noqa: E402
cfb._pfad().write_text(json.dumps({"version": 1, "bereiche": [
    {"id": "alt1", "typ": "space", "key": "CTDP", "name": "Alt", "inkl_unter": True}]}),
    encoding="utf-8")
r = lauf(C)
check("Altbestand ohne Wissensgruppe: kein Abruf, keine Datei",
      C.page_rufe == [] and dateien() == [], str(C.page_rufe))
check("und der Grund steht beim Eintrag",
      "Wissensgruppe" in ((stand()["eintraege"].get("alt1") or {}).get("fehler") or ""))


# ════════════════════════════════════════════════════════════════════════════
section("9. Kaputter Stand: Lauf bricht ab, statt neu anzufangen")
cfa._pfad().write_text("{ kaputt", encoding="utf-8")
r = sicher(cfa.lauf, client=C, aktiv=(True, ""))
check("lauf() wirft nicht", isinstance(r, dict), str(r))
check("⚠ und meldet den Fehler, statt mit leerem Stand weiterzuarbeiten",
      isinstance(r, dict) and "fehlgeschlagen" in r.get("grund", ""), str(r))
check("die kaputte Datei bleibt, wie sie war", cfa._pfad().read_text() == "{ kaputt")
cfa._pfad().unlink()


# ════════════════════════════════════════════════════════════════════════════
section("9b. Unlesbare EINBINDUNG: nichts wird abgeraeumt, nichts ueberschrieben")
# ⚠ Code-Review 2026-09-28: `_laden` gab bei einer unlesbaren Ablage `_leer()`
# zurueck - der Abgleich hielt damit KEINE Seite mehr fuer gewollt und loeschte
# jede importierte Confluence-Seite; hinzufuegen/aendern schrieben den leeren
# Stand plus den neuen Eintrag ueber die Datei.
_b_vor = cfb._pfad().read_bytes() if cfb._pfad().is_file() else None
if cfb._pfad().is_file():
    cfb._pfad().unlink()
e9 = cfb.hinzufuegen([{"key": "CTDP", "seiten": ["100"]}], "tester", ["technik"])
lauf(C)
_fs9 = dateien()
check("(Positivkontrolle) es gibt importiertes Wissen, das verloren gehen koennte",
      any("100_" in f for f in _fs9), str(_fs9))
KAPUTT_B = b'{"version": 1, "bereiche": [ kein json'
cfb._pfad().write_bytes(KAPUTT_B)
_st9 = cfa._pfad().read_bytes()
r = sicher(cfa.lauf, client=C, aktiv=(True, ""))
check("lauf() wirft nicht und meldet den Fehler",
      isinstance(r, dict) and "fehlgeschlagen" in r.get("grund", ""), str(r))
check("⚠ kein importiertes Wissen geloescht", dateien() == _fs9, str(dateien()))
check("⚠ der Abgleichsstand ist unveraendert", cfa._pfad().read_bytes() == _st9)
for _nm, _fn in [("hinzufuegen", lambda: cfb.hinzufuegen([{"key": "OPS", "start": True}], "x", ["technik"])),
                 ("aendern", lambda: cfb.aendern(e9["id"], [{"key": "OPS", "start": True}], "x", ["technik"])),
                 ("entfernen", lambda: cfb.entfernen(e9["id"]))]:
    _r = sicher(_fn)
    check(f"⚠ {_nm} verweigert mit BestandUnlesbar",
          isinstance(_r, getattr(cfb, "BestandUnlesbar", ())), repr(_r))
    check(f"⚠ {_nm} laesst die unlesbare Datei, wie sie war", cfb._pfad().read_bytes() == KAPUTT_B)
for _form in (b'[]', b'{"bereiche": {}}'):
    cfb._pfad().write_bytes(_form)
    check(f"formwidrige Ablage {_form.decode()} gilt ebenfalls als unlesbar",
          isinstance(sicher(cfb.liste), getattr(cfb, "BestandUnlesbar", ())))
# Gegenstueck: eine FEHLENDE Ablage ist wirklich "nichts eingebunden" - dann
# raeumt der Lauf ab. Belegt zugleich, dass der Aufbau oben Zaehne hat.
cfb._pfad().unlink()
lauf(C)
check("(Gegenstueck) ohne Ablage wird das Wissen abgeraeumt", dateien() == [], str(dateien()))
if _b_vor is not None:
    cfb._pfad().write_bytes(_b_vor)
cfa._pfad().unlink()


# ════════════════════════════════════════════════════════════════════════════
section("10. Verdrahtung im Cron-Auftrag (AST)")
SCH = (ROOT / "backend" / "scheduler.py").read_text(encoding="utf-8")
baum = ast.parse(SCH)
zweig = None
for n in ast.walk(baum):
    if isinstance(n, ast.If) and "wissensabgleich" in ast.unparse(n.test):
        zweig = n
check("(Positivkontrolle) der Zweig kind == 'wissensabgleich' ist gefunden", zweig is not None)
# ⚠ NUR DER RUMPF: ein `elif` traegt die folgenden Zweige in `orelse` – der
# Agenten-Zweig dahinter gehoert nicht zu diesem.
koerper = ast.Module(body=list(zweig.body), type_ignores=[]) if zweig else None
rufe = []
for n in ast.walk(koerper) if koerper else []:
    if isinstance(n, ast.Attribute) and n.attr == "lauf" and isinstance(n.value, ast.Name):
        rufe.append((n.lineno, n.col_offset, n.value.id))
rufe.sort()
namen = [r[2] for r in rufe]
check("der Zweig ruft confluence_abgleich.lauf", "confluence_abgleich" in namen, str(namen))
check("⚠ ERST Confluence, DANN der Index (sonst liegt jede Aenderung einen Takt brach)",
      "confluence_abgleich" in namen and "rag_autoindex" in namen
      and namen.index("confluence_abgleich") < namen.index("rag_autoindex"), str(namen))
check("⚠ der Zweig startet keinen Agenten",
      koerper is not None and "run_task_headless" not in ast.unparse(koerper)
      and "run_task_headless" in ast.unparse(zweig))   # Positivkontrolle: der Schnitt trennt wirklich
check("die Stand-Datei steht in den Sperrlisten",
      "confluence_abgleich.json" in (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════════════════
section("11. Tag-Filter je Eintrag (Vorgabe 2026-09-27)")
F = cfa.tags_filtern
L = [{"id": "1", "labels": ["handbuch"]}, {"id": "2", "labels": []},
     {"id": "3", "labels": ["intern", "handbuch"]}, {"id": "4", "labels": None}]
check("leere Tags = kein Filter", F({"1", "2"}, L, []) == {"1", "2"})
check("nur Seiten mit mindestens einem Tag", F({"1", "2", "3"}, L, ["handbuch"]) == {"1", "3"})
check("ODER-Verknuepfung ueber mehrere Tags", F({"1", "2", "3"}, L, ["intern", "gibtsnicht"]) == {"3"})
check("Gross-/Kleinschreibung spielt keine Rolle", F({"1"}, L, ["HANDBUCH"]) == {"1"})
check("⚠ Labels UNBEKANNT (None) -> None, nicht 'kein Tag'", F({"1", "4"}, L, ["handbuch"]) is None)
check("unbekannte Labels ausserhalb der Auswahl stoeren nicht", F({"1"}, L, ["handbuch"]) == {"1"})
check("ohne Filter sind auch unbekannte Labels egal", F({"4"}, L, []) == {"4"})

C = Attrappe()
C.seite("DOC", "700", "Wurzel")
C.seite("DOC", "701", "Handbuch Teil 1", parent="700", labels=["Handbuch"])
C.seite("DOC", "702", "Notiz", parent="700")
C.seite("DOC", "703", "Handbuch Teil 2", parent="700", labels=["handbuch", "intern"])
C.seite("DOC", "704", "Nur intern", parent="700", labels=["intern"])
et = cfb.hinzufuegen([{"key": "DOC", "start": True, "ganz": True}], "tester", ["technik"],
                     None, ["Handbuch"])
check("(Positivkontrolle) Eintrag mit Tag angelegt", et.get("tags") == ["handbuch"], str(et))
r = lauf(C)
fs = dateien()
check("⚠ die Labels werden MIT der Seitenliste verlangt", C.label_rufe == [True], str(C.label_rufe))
check("⚠ nur getaggte Seiten kommen ins Wissen", sorted(f.split("/")[-1][:3] for f in fs) == ["701", "703"], str(fs))
check("⚠ ungetaggte Seiten werden nicht einmal geholt",
      not ({"700", "702", "704"} & set(C.page_rufe)), str(C.page_rufe))
check("die Zaehlung am Eintrag nennt die gefilterten Seiten",
      (stand()["eintraege"].get(et["id"]) or {}).get("seiten") == 2, str(stand()["eintraege"]))

# Tag an einer Seite ENTFERNT, an einer anderen GESETZT – ohne Versionswechsel.
C.raeume["DOC"]["701"]["labels"] = []
C.raeume["DOC"]["702"]["labels"] = ["handbuch"]
r = lauf(C)
fs = dateien()
check("⚠ Tag entfernt (Version gleich): die Seite verschwindet aus dem Wissen",
      not any("/701_" in f for f in fs), str(fs))
check("⚠ Tag gesetzt (Version gleich): die Seite kommt ins Wissen", any("/702_" in f for f in fs), str(fs))
check("die unveraenderte getaggte Seite wird nicht neu geholt", "703" not in C.page_rufe, str(C.page_rufe))

# ⚠ Labels unbekannt: NICHTS loeschen.
vorher = dateien()
C.ohne_labels.add("DOC")
r = lauf(C)
check("(Positivkontrolle) die Antwort trug wirklich keine Labels", C.label_rufe == [True])
check("⚠ Labels unbekannt: kein getaggtes Wissen verschwindet", dateien() == vorher, f"{vorher} -> {dateien()}")
check("und der Eintrag nennt den Grund",
      "nicht lesbar" in ((stand()["eintraege"].get(et["id"]) or {}).get("fehler") or ""), str(stand()["eintraege"]))
C.ohne_labels.clear()

# Zwei Eintraege auf DENSELBEN Bereich: einer mit Tag, einer ohne.
eo = cfb.hinzufuegen([{"key": "DOC", "seiten": ["704"]}], "tester", ["vertrieb"])
r = lauf(C)
fs = dateien()
check("ein Eintrag OHNE Tags nimmt seine Seite ungefiltert", any("/704_" in f for f in fs), str(fs))
check("⚠ und sie traegt nur SEINE Gruppe (der getaggte Eintrag deckt sie nicht ab)",
      [v for k, v in ZUORDNUNG.items() if "704_" in k] == [["vertrieb"]], str(ZUORDNUNG))
cfb.entfernen(eo["id"])

# Tags weg: der ganze markierte Bereich kommt.
cfb.aendern(et["id"], [{"key": "DOC", "start": True, "ganz": True}], "tester", ["technik"], None, [])
C.start["DOC"] = "700"
r = lauf(C)
check("⚠ Tag-Liste leer: alle markierten Seiten des Bereichs kommen",
      sorted(f.split("/")[-1][:3] for f in dateien()) == ["700", "701", "702", "703", "704"], str(dateien()))
check("⚠ ohne Tags werden KEINE Labels verlangt (Abruf wie vor dem Filter)",
      C.label_rufe == [False], str(C.label_rufe))
cfb.entfernen(et["id"]); lauf(C)
check("(Aufraeumen) Wissen leer", dateien() == [], str(dateien()))

# Kaputte Tag-Angabe in der Ablage: der Eintrag wird NICHT ungefiltert abgeglichen.
cfb._pfad().write_text(json.dumps({"version": 1, "bereiche": [
    {"id": "k1", "typ": "auswahl", "name": "K", "gruppen": ["technik"], "tags": "handbuch",
     "auswahl": [{"key": "DOC", "start": True, "ganz": True, "seiten": [], "zweige": []}]}]}),
    encoding="utf-8")
r = lauf(C)
check("⚠ kaputte Tags: kein Abruf, kein Wissen (statt des ganzen Bereichs)",
      C.page_rufe == [] and dateien() == [], str(C.page_rufe))
check("und der Grund steht beim Eintrag",
      "Tags" in ((stand()["eintraege"].get("k1") or {}).get("fehler") or ""), str(stand()["eintraege"]))
cfb._pfad().unlink(); lauf(C)


# ════════════════════════════════════════════════════════════════════════════
section("12. Der echte Client liest die Labels (Antwortform von /rest/api/content)")
import importlib  # noqa: E402
sys.modules.pop("backend.confluence_client", None)
cc = importlib.import_module("backend.confluence_client")
kl = cc.ConfluenceClient({"base_url": "https://cf.invalid", "api_token": "x"})
PARAMS: list = []
def _req(method, path, params=None, **kw):
    PARAMS.append(dict(params or {}))
    return {"_links": {"base": "https://cf.invalid"}, "results": [
        {"id": "1", "title": "A", "_links": {"webui": "/a"},
         "metadata": {"labels": {"results": [{"prefix": "global", "name": "Handbuch"},
                                             {"prefix": "my", "name": "privat"}]}}},
        {"id": "2", "title": "B", "_links": {}, "metadata": {"labels": {"results": []}}},
        {"id": "3", "title": "C", "_links": {}}]}
kl._request = _req
mit = kl.pages_in_space("DOC", 50, with_labels=True)
check("expand verlangt metadata.labels", "metadata.labels" in (PARAMS[-1].get("expand") or ""), str(PARAMS[-1]))
check("die Label-Namen kommen klein geschrieben", mit[0].get("labels") == ["handbuch", "privat"], str(mit[0]))
check("eine Seite ohne Labels hat die LEERE Liste", mit[1].get("labels") == [], str(mit[1]))
check("⚠ fehlt metadata ganz, steht None da (unbekannt, nicht 'keine')",
      "labels" in mit[2] and mit[2]["labels"] is None, str(mit[2]))
ohne = kl.pages_in_space("DOC", 50, with_parent=True, with_version=True)
check("⚠ ohne with_labels kein metadata im expand (Abruf unveraendert)",
      "metadata" not in (PARAMS[-1].get("expand") or "") and "labels" not in ohne[0], str(PARAMS[-1]))

section("12b. Blaettern: _links.next statt 'weniger als verlangt' (Code-Review 2026-10-07)")
ALLE = [{"id": str(i), "title": "S%d" % i, "_links": {"webui": "/p/%d" % i}} for i in range(60)]


def _server(kappen=25, mit_links=True, filtern=None):
    """Antwortform von /rest/api/content: kappt das limit (wie bei expand),
    filtert optional NACH dem Limit (Rechte) – nennt aber _links.next."""
    rufe = []

    def _r(method, path, params=None, **kw):
        p = dict(params or {})
        rufe.append(p)
        st, lim = int(p.get("start", 0)), min(int(p.get("limit", 50)), kappen)
        teil = ALLE[st:st + lim]
        sichtbar = [x for x in teil if not (filtern and filtern(x))]
        d = {"results": sichtbar, "start": st, "limit": lim, "size": len(sichtbar)}
        if mit_links:
            d["_links"] = {"base": "https://cf.invalid"}
            if st + lim < len(ALLE):
                d["_links"]["next"] = "/rest/api/content?start=%d" % (st + lim)
        return d
    return _r, rufe


for name, srv, soll in (
        ("Server kappt limit auf 25 (mit _links.next)", _server(25), 60),
        ("Server kappt limit, ohne _links (limit aus der Antwort)", _server(25, mit_links=False), 60),
        ("Rechtefilter nach dem Limit (Seite kuerzer, next vorhanden)",
         _server(50, filtern=lambda x: x["id"] in ("3", "7", "11")), 57),
        ("ganzes Fenster weggefiltert (leere Seite MIT next)",
         _server(25, filtern=lambda x: 25 <= int(x["id"]) < 50), 35)):
    kl._request, rufe = srv
    erg = kl.pages_in_space("DOC", 500)
    ids = [x["id"] for x in erg]
    check("⚠ %s: alle %d Seiten, keine doppelt" % (name, soll),
          len(ids) == soll and len(set(ids)) == soll, "%d Seiten, %d Abrufe" % (len(ids), len(rufe)))
kl._request, rufe = _server(50)
erg = kl.pages_in_space("DOC", 500)
check("Positivkontrolle: ohne Kappung zwei Abrufe, 60 Seiten, dann Schluss",
      len(erg) == 60 and len(rufe) == 2, "%d / %d" % (len(erg), len(rufe)))
kl._request, rufe = _server(25)
sp = kl.spaces_detailed(500)
check("spaces_detailed blaettert genauso (60 bei gekapptem limit)", len(sp) == 60, str(len(sp)))


# ════════════════════════════════════════════════════════════════════════════
section("13. Datum des letzten Imports (Vorgabe 2026-09-28)")
import os as _os  # noqa: E402
import time as _time  # noqa: E402
for p_ in (cfb._pfad(), cfa._pfad()):
    if p_.is_file():
        p_.unlink()
shutil.rmtree(SAND / "rag", ignore_errors=True); ORDNER_A.mkdir(parents=True); ORDNER_B.mkdir(parents=True)
C = Attrappe()
C.seite("IMP", "500", "Wurzel")
C.seite("IMP", "501", "Kind", parent="500")
C.seite("ZWO", "600", "Anderswo")
e13 = cfb.hinzufuegen([{"key": "IMP", "seiten": ["500"], "zweige": ["500"]},
                       {"key": "ZWO", "seiten": ["600"]}], "tester", ["technik"])
check("(Positivkontrolle) Eintrag angelegt", isinstance(e13, dict), str(e13))
vor = _time.strftime("%Y-%m-%dT%H:%M:%S")
r = lauf(C)
check("(Positivkontrolle) drei Seiten importiert", r.get("neu") == 3, str(r))
st = stand()["seiten"]
check("⚠ der Stand fuehrt je importierter Seite die Zeit (ISO, Sekunden)",
      all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", str((st.get(k) or {}).get("zeit") or ""))
          for k in ("500", "501", "600")), str(st))
check("die Zeit ist die des Laufs", str((st.get("500") or {}).get("zeit") or "") >= vor, str(st.get("500")))
iz = cfa.import_zeiten()
check("import_zeiten() nennt jede Seite", sorted(iz["seiten"]) == ["500", "501", "600"], str(iz))
check("import_zeiten() nennt jeden Bereich", sorted(iz["bereiche"]) == ["IMP", "ZWO"], str(iz))

# Unveraendert: die Zeit bleibt (sie ist die des WIRKLICHEN Imports)
for k in st:
    st[k]["zeit"] = "2026-01-02T03:04:05"
st["501"]["zeit"] = "2026-01-05T00:00:00"
d_ = stand(); d_["seiten"] = st; cfa._stand_speichern(d_)
lauf(C)
st = stand()["seiten"]
check("⚠ ein Takt ohne Aenderung laesst die Importzeit stehen",
      (st.get("500") or {}).get("zeit") == "2026-01-02T03:04:05", str(st.get("500")))
iz = cfa.import_zeiten()
check("⚠ je Bereich steht der JUENGSTE Import seiner Seiten",
      iz["bereiche"].get("IMP") == "2026-01-05T00:00:00", str(iz["bereiche"]))
# ⚠ BEIDE REIHENFOLGEN: die Seiten stehen im Stand in Mengen-Reihenfolge; ohne
# echten Vergleich gewaenne sonst zufaellig die zuletzt gelesene Seite.
for reihe in (("jung", "alt"), ("alt", "jung")):
    zt = {"jung": "2026-03-03T00:00:00", "alt": "2026-02-02T00:00:00"}
    d_ = stand()
    d_["seiten"] = {f"x{i}": {"space": "REIHE", "zeit": zt[w], "datei": ""}
                    for i, w in enumerate(reihe)}
    sichern = stand()
    cfa._stand_speichern(d_)
    check(f"⚠ juengster Import gewinnt unabhaengig von der Reihenfolge ({'/'.join(reihe)})",
          cfa.import_zeiten()["bereiche"].get("REIHE") == zt["jung"], str(cfa.import_zeiten()))
    cfa._stand_speichern(sichern)
C.seite("IMP", "500", "Wurzel", version=2)
lauf(C)
st = stand()["seiten"]
check("eine geaenderte Seite bekommt eine NEUE Importzeit",
      str((st.get("500") or {}).get("zeit") or "") >= vor, str(st.get("500")))
check("…die unveraenderte Nachbarseite nicht",
      (st.get("501") or {}).get("zeit") == "2026-01-05T00:00:00", str(st.get("501")))

# Altbestand ohne `zeit`: Aenderungszeit der Datei; ohne Datei kein Datum
d_ = stand()
d_["seiten"]["600"].pop("zeit", None)
datei600 = SAND / d_["seiten"]["600"]["datei"]
_os.utime(datei600, (1767323045, 1767323045))
d_["seiten"]["501"].pop("zeit", None)
(SAND / d_["seiten"]["501"]["datei"]).unlink()
cfa._stand_speichern(d_)
iz = cfa.import_zeiten()
from datetime import datetime as _dt  # noqa: E402
check("⚠ Altbestand ohne Zeit: es gilt die Aenderungszeit der Datei",
      iz["seiten"].get("600") == _dt.fromtimestamp(1767323045).isoformat(timespec="seconds"), str(iz))
check("⚠ Altbestand ohne Zeit UND ohne Datei: KEIN Datum (nicht raten)",
      "501" not in iz["seiten"], str(iz))

# Abgewaehlt -> entfernt -> kein Datum mehr
cfb.aendern(e13["id"], [{"key": "IMP", "seiten": ["500"]}], "tester", ["technik"])
lauf(C)
iz = cfa.import_zeiten()
check("abgewaehlte Seite / Bereich: kein Datum mehr",
      "600" not in iz["seiten"] and "ZWO" not in iz["bereiche"], str(iz))

# Unlesbarer Stand: leer, kein Wurf
cfa._pfad().write_text("{kaputt", encoding="utf-8")
iz = sicher(cfa.import_zeiten)
check("unlesbarer Stand: import_zeiten() wirft nicht und liefert leer",
      iz == {"seiten": {}, "bereiche": {}}, str(iz))
cfa._pfad().unlink()


# ── Aufraeumen ──────────────────────────────────────────────────────────────
shutil.rmtree(SAND, ignore_errors=True)
check("⚠ die echte Einbindung ist unveraendert",
      (ECHT_B.read_bytes() if ECHT_B.is_file() else None) == ECHT_B_VOR)
check("⚠ der echte Abgleichsstand ist unveraendert",
      (ECHT_A.read_bytes() if ECHT_A.is_file() else None) == ECHT_A_VOR)

print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
sys.exit(1 if FAIL else 0)
