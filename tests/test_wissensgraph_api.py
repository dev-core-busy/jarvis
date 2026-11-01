#!/usr/bin/env python3
"""Wissensgraph: Ansicht, Detail, Pruefliste und Admin-Entscheidungen.

Ausgefuehrt gegen einen Sandkasten-Graphen (``backend.config`` als Attrappe):
  1. ``ansicht``: Filter Art/Ordner/Gruppe/Dokumente, Suche liefert Treffer
     SAMT Nachbarn, Sortierung nach Grad, Seiten, Kanten nur zwischen
     ausgelieferten Knoten.
  2. ``knoten_detail``: ein- und ausgehende Kanten mit Namen.
  3. Zusammenfuehren/Trennen/Loeschen ueberstehen einen NEUAUFBAU (die
     Ableitung liest aliasse.json bei jedem Aufbau), Kreis und Dokumentknoten
     werden abgewiesen, Trennen nimmt eine Zusammenfuehrung zurueck.
  4. Pruefliste: nur Paare ab der Schwelle, nie gleiche Normform, nie ein
     getrenntes Paar; Vorschlag: der kleinere geht im groesseren auf.
  5. Die Seitenroute liefert die Seite; alle Daten-Routen sind admin-only
     (Regel in test_endpoint_rights).

    python3 tests/test_wissensgraph_api.py
"""
import ast
import hashlib
import sys
import tempfile
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
    import numpy as np
    from backend import wissensgraph as wg
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)
for n in ("ansicht", "knoten_detail", "zusammenfuehren", "trennen", "knoten_loeschen", "pruefliste"):
    if not hasattr(wg, n):
        print(f"ABBRUCH – wissensgraph.{n} fehlt")
        sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="wg_api_"))
wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)


def ent(n, typ="system"):
    return {"name": n, "typ": typ, "beschreibung": "zu " + n}


def rel(a, b, art="nutzt"):
    return {"von": a, "nach": b, "art": art}


# Zwei Ordner, drei Dokumente. "Drucker" kommt in allen vor (Grad hoch).
wg.quelle_schreiben("data/rag/a/1.md", 1, [ent("Drucker"), ent("Server"), ent("Abrechnung", "prozess")],
                    [rel("Drucker", "Server"), rel("Abrechnung", "Drucker")])
wg.quelle_schreiben("data/rag/a/2.md", 1, [ent("Drucker"), ent("Druckserver"), ent("Kasse", "ort")],
                    [rel("Druckserver", "Drucker")])
wg.quelle_schreiben("data/rag/b/3.md", 1, [ent("Drucker"), ent("Labor", "konzept"), ent("Einsam", "ort")],
                    [rel("Labor", "Drucker")])

section("1. Ansicht")
g = wg.ansicht()
ids = {k["id"] for k in g["knoten"]}
check("Positivkontrolle: alle Begriffe und 3 Dokumente", len(ids) == 10 and g["gefiltert"] == 10, sorted(ids))
check("nach Grad sortiert (Drucker zuerst)", g["knoten"][0]["id"] == "e:drucker", g["knoten"][0]["id"])
check("Kanten nur zwischen ausgelieferten Knoten",
      all(e["von"] in ids and e["nach"] in ids for e in g["kanten"]))
g = wg.ansicht(dokumente=False)
check("ohne Dokumente: keine Dokumentknoten", all(k["typ"] != "quelle" for k in g["knoten"]) and len(g["knoten"]) == 7)
g = wg.ansicht(typ="ort", dokumente=False)
check("Filter Art", {k["id"] for k in g["knoten"]} == {"e:kasse", "e:einsam"}, [k["id"] for k in g["knoten"]])
g = wg.ansicht(ordner="data/rag/b", dokumente=False)
check("Filter Ordner: nur Begriffe mit einer Quelle darunter",
      {k["id"] for k in g["knoten"]} == {"e:drucker", "e:labor", "e:einsam"}, [k["id"] for k in g["knoten"]])
g = wg.ansicht(ordner="data/rag/a", dokumente=False)
check("Praefix mit Trenner (a trifft nicht ab)", "e:labor" not in {k["id"] for k in g["knoten"]})
import backend.knowledge_groups as kg  # noqa: E402
_alt = kg.filter_paths_by_groups
kg.filter_paths_by_groups = lambda pfade, gids: [p for p in pfade if p.startswith("data/rag/b/")] if gids == ["g"] else list(pfade)
g = wg.ansicht(gruppe="g", dokumente=False)
kg.filter_paths_by_groups = _alt
check("Filter Wissensgruppe (ueber filter_paths_by_groups)",
      {k["id"] for k in g["knoten"]} == {"e:drucker", "e:labor", "e:einsam"}, [k["id"] for k in g["knoten"]])
g = wg.ansicht(q="druckserv", dokumente=False)
check("Suche: Treffer markiert", g["treffer"] == ["e:druckserver"], g["treffer"])
check("Suche: Treffer SAMT Nachbarn", {k["id"] for k in g["knoten"]} == {"e:druckserver", "e:drucker"},
      [k["id"] for k in g["knoten"]])
g1 = wg.ansicht(limit=4, offset=0)
g2 = wg.ansicht(limit=4, offset=4)
check("Seiten: verschiedene Knoten, gefiltert gesamt", not ({k["id"] for k in g1["knoten"]} & {k["id"] for k in g2["knoten"]})
      and g1["gefiltert"] == 10 and len(g1["knoten"]) == 4)
# Erst auf einer SEITE kann eine Kante ins Leere zeigen – in der Vollansicht
# hat jede Kante beide Enden, die Pruefung dort waere trivial wahr.
ids1 = {k["id"] for k in g1["knoten"]}
check("Positivkontrolle: die Seite schneidet Kanten ab",
      sum(1 for e in wg.graph()["kanten"] if (e["von"] in ids1) != (e["nach"] in ids1)) > 0)
check("auf einer Seite: Kanten nur zwischen ausgelieferten Knoten",
      all(e["von"] in ids1 and e["nach"] in ids1 for e in g1["kanten"]), len(g1["kanten"]))
# Praefix-Falle: ein Nachbarordner, dessen Name mit dem gefilterten beginnt.
wg.quelle_schreiben("data/rag/ab/4.md", 1, [ent("Fremdling")], [])
g = wg.ansicht(ordner="data/rag/a", dokumente=False)
check("Ordner a trifft nicht ab (Praefix mit Trenner)", "e:fremdling" not in {k["id"] for k in g["knoten"]},
      [k["id"] for k in g["knoten"]])
wg.quellen_entfernen(["data/rag/ab/4.md"])

section("2. Detail")
d = wg.knoten_detail("e:drucker")
check("Detail vorhanden", d is not None and d["name"] == "Drucker")
check("eingehende Kanten mit Namen",
      d is not None and {x["name"] for x in d["eingehend"]} >= {"Abrechnung", "Druckserver", "Labor"},
      d and [x["name"] for x in d["eingehend"]])
check("ausgehende Kanten (zu Dokumenten und Server)",
      d is not None and any(x["name"] == "Server" for x in d["ausgehend"]))
check("unbekannter Knoten → None", wg.knoten_detail("e:gibtsnicht") is None)

section("3. Entscheidungen ueberstehen einen Neuaufbau")
wg.zusammenfuehren("e:druckserver", "e:drucker")
wg._zuruecksetzen_fuer_test()                       # "Neuaufbau": nur die Platte zaehlt
ids = {k["id"] for k in wg.graph()["knoten"]}
check("zusammengefuehrt: Quelle verschwindet, Ziel bleibt", "e:druckserver" not in ids and "e:drucker" in ids)
dr = wg.knoten_detail("e:drucker")
check("die Schreibweise der Quelle wird Alias", dr is not None and "Druckserver" in dr["aliasse"], dr and dr["aliasse"])
try:
    wg.zusammenfuehren("e:drucker", "e:druckserver")
    kreis = False
except ValueError:
    kreis = True
check("Kreis wird abgewiesen", kreis)
try:
    wg.zusammenfuehren("q:data/rag/a/1.md", "e:drucker")
    dok = False
except ValueError:
    dok = True
check("Dokumentknoten lassen sich nicht zusammenfuehren", dok)
wg.trennen("e:druckserver", "e:drucker")
wg._zuruecksetzen_fuer_test()
check("Trennen nimmt die Zusammenfuehrung zurueck", "e:druckserver" in {k["id"] for k in wg.graph()["knoten"]})
wg.knoten_loeschen("e:einsam")
wg._zuruecksetzen_fuer_test()
check("geloescht bleibt geloescht", "e:einsam" not in {k["id"] for k in wg.graph()["knoten"]})
try:
    wg.knoten_loeschen("q:data/rag/b/3.md")
    dok = False
except ValueError:
    dok = True
check("ein Dokument loescht man nicht hier", dok)

section("4. Pruefliste")
# Kodierer-Attrappe: Druck* liegen nah beieinander, der Rest weit weg.
NAH = {"drucker": 0, "druckserver": 0}


def kodieren(namen):
    raus = []
    for n in namen:
        nn = wg.norm_name(n)
        if nn in NAH:
            v = np.zeros(16, "float32")
            v[0] = 1.0
            v[1] = 0.05 if nn == "druckserver" else 0.0
        else:
            h = hashlib.sha256(nn.encode()).digest()[:16]
            v = np.frombuffer(h, dtype=np.uint8).astype("float32") - 127.5
        raus.append(v / np.linalg.norm(v))
    return np.stack(raus)


wg._zuruecksetzen_fuer_test()
p = wg.pruefliste(kodieren=kodieren)
paare = {tuple(sorted([x["quelle"]["id"], x["ziel"]["id"]])) for x in p}
check("ein getrenntes Paar erscheint nicht wieder", ("e:drucker", "e:druckserver") not in paare, p)
d = wg._roh_aliasse()
d["getrennt"] = []
wg._aliasse_schreiben(d)
wg._zuruecksetzen_fuer_test()
p = wg.pruefliste(kodieren=kodieren)
paare = [tuple(sorted([x["quelle"]["id"], x["ziel"]["id"]])) for x in p]
check("ohne Entscheidung: das nahe Paar steht in der Liste", ("e:drucker", "e:druckserver") in paare, p)
check("nur Paare ab der Schwelle", all(x["aehnlichkeit"] >= wg.PRUEF_SCHWELLE for x in p), p)
check("Vorschlag: der kleinere geht im groesseren auf",
      bool(p) and p[0]["quelle"]["id"] == "e:druckserver" and p[0]["ziel"]["id"] == "e:drucker", p[:1])
check("nie ein Paar gleicher Normform", all(x["quelle"]["id"] != x["ziel"]["id"] for x in p))

section("4b. Pruefliste: vektorisiert = alte Schleife, Stand gepuffert")


def referenz(limit, kod, schwelle):
    """Die fruehere Schleife (bis 2026-10-31) – gegen sie wird verglichen."""
    g = wg.graph()
    ent = [k for k in g["knoten"] if k["typ"] != wg.TYP_QUELLE]
    V = np.stack([np.asarray(v, "float32") for v in kod([k["name"] for k in ent])])
    getrennt = {tuple(sorted(x)) for x in wg._roh_aliasse()["getrennt"]}
    paare = []
    for i0 in range(0, len(ent), 500):
        S = V[i0:i0 + 500] @ V.T
        for di, j in zip(*np.where(S >= schwelle)):
            i = i0 + int(di)
            if j <= i:
                continue
            a, b = ent[i], ent[int(j)]
            if tuple(sorted([a["id"][2:], b["id"][2:]])) in getrennt:
                continue
            paare.append((float(S[di, j]), a, b))
    paare.sort(key=lambda t: -t[0])
    return [(round(x, 3), tuple(sorted([a["id"], b["id"]]))) for x, a, b in paare[:limit]]


# Viele nahe Paare: 40 Begriffe auf 8 Achsen, je Achse leicht verschoben –
# dazu exakte Gleichstaende (gleiche Vektoren) und ein getrenntes Paar.
rng = np.random.default_rng(7)
ACHSEN = rng.normal(size=(8, 16)).astype("float32")
VEK = {}
namen_viel = [f"Begriff {i:02d}" for i in range(40)]
for i, nm in enumerate(namen_viel):
    v = ACHSEN[i % 8] + (0.0 if i % 5 == 0 else 0.08 * rng.normal(size=16).astype("float32"))
    VEK[wg.norm_name(nm)] = v / np.linalg.norm(v)


def kod_viel(namen):
    return np.stack([VEK.get(wg.norm_name(n), kodieren([n])[0]) for n in namen])


wg.quelle_schreiben("data/rag/a/viel.md", 1, [ent(nm) for nm in namen_viel], [])
d = wg._roh_aliasse()
d["getrennt"] = [["begriff 00", "begriff 08"]]
wg._aliasse_schreiben(d)
wg._zuruecksetzen_fuer_test()
for lim, schw in ((5, 0.88), (30, 0.88), (200, 0.5)):
    wg._zuruecksetzen_fuer_test()
    neu = [(x["aehnlichkeit"], tuple(sorted([x["quelle"]["id"], x["ziel"]["id"]])))
           for x in wg.pruefliste(lim, kodieren=kod_viel, schwelle=schw)]
    ref = referenz(lim, kod_viel, schw)
    check(f"limit {lim}, Schwelle {schw}: dieselben Paare wie die alte Schleife ({len(ref)})",
          [p for _s, p in neu] == [p for _s, p in ref] and [s_ for s_, _p in neu] == [s_ for s_, _p in ref],
          (neu[:3], ref[:3]))
check("Positivkontrolle: der Vergleich hatte Gleichstaende und viele Paare",
      len(referenz(200, kod_viel, 0.5)) > 50)
# Der Vorrat (limit + getrennte) zaehlt nur, wenn ein getrenntes Paar unter den
# BESTEN liegt – sonst fuellen die naechsten ohnehin auf (Gegenprobe war stumm).
_spitze = referenz(1, kod_viel, 0.88)[0][1]
_d = wg._roh_aliasse()
_alt_getrennt = [list(x) for x in _d["getrennt"]]
_d["getrennt"] = _alt_getrennt + [[_spitze[0][2:], _spitze[1][2:]]]
wg._aliasse_schreiben(_d)
wg._zuruecksetzen_fuer_test()
_neu5 = [tuple(sorted([x["quelle"]["id"], x["ziel"]["id"]])) for x in wg.pruefliste(5, kodieren=kod_viel, schwelle=0.88)]
_ref5 = [p_ for _s, p_ in referenz(5, kod_viel, 0.88)]
check("getrenntes Spitzenpaar: die Liste fuellt trotzdem voll auf (Vorrat)",
      len(_neu5) == 5 and _neu5 == _ref5 and _spitze not in _neu5, (_spitze, _neu5, _ref5))
_d["getrennt"] = _alt_getrennt
wg._aliasse_schreiben(_d)
wg._zuruecksetzen_fuer_test()
check("getrenntes Paar fehlt auch vektorisiert",
      ("e:begriff 00", "e:begriff 08") not in {tuple(sorted([x["quelle"]["id"], x["ziel"]["id"]]))
                                            for x in wg.pruefliste(200, kodieren=kod_viel, schwelle=0.5)})

wg._zuruecksetzen_fuer_test()
gestartet = []
st = wg.pruefliste_stand(10, starten=gestartet.append)
check("Stand ohne Rechnung: sofort leer mit 'laeuft'", st["paare"] == [] and st["laeuft"] and len(gestartet) == 1, st)
st2 = wg.pruefliste_stand(10, starten=gestartet.append)
check("hoechstens EIN Hintergrundlauf zugleich", len(gestartet) == 1 and st2["laeuft"], len(gestartet))
_echt_pl = wg.pruefliste
wg.pruefliste = lambda lim, **kw: _echt_pl(lim, kodieren=kod_viel, schwelle=0.5)
gestartet[0]()
wg.pruefliste = _echt_pl
st3 = wg.pruefliste_stand(10, starten=gestartet.append)
check("nach der Rechnung: Paare, aktuell, kein neuer Lauf",
      len(st3["paare"]) == 10 and not st3["laeuft"] and not st3["veraltet"] and len(gestartet) == 1, st3)
erstes = st3["paare"][0] if st3["paare"] else None
try:
    # Eine falsche Liste (etwa ein Selbstpaar) darf hier nicht ABBRECHEN, sondern
    # muss als FAIL mit Bilanz erscheinen (Gegenprobe "Diagonale" brach ab).
    wg.trennen(erstes["quelle"]["id"], erstes["ziel"]["id"])
    getrennt_ok = True
except Exception as _e:  # noqa: BLE001
    getrennt_ok = False
    erstes = erstes or {"quelle": {"id": ""}, "ziel": {"id": ""}}
check("Positivkontrolle: das erste Paar laesst sich trennen", getrennt_ok)
st4 = wg.pruefliste_stand(10, starten=gestartet.append)
check("getrennt: Paar faellt sofort aus dem (veralteten) Stand",
      all({x["quelle"]["id"], x["ziel"]["id"]} != {erstes["quelle"]["id"], erstes["ziel"]["id"]} for x in st4["paare"]),
      st4["paare"][:2])
check("Graph geaendert: Stand gilt als veraltet und es wird neu gerechnet",
      st4["veraltet"] and len(gestartet) == 2, (st4["veraltet"], len(gestartet)))
zweites = st4["paare"][0] if st4["paare"] else {"quelle": {"id": ""}, "ziel": {"id": ""}}
try:
    wg.zusammenfuehren(zweites["quelle"]["id"], zweites["ziel"]["id"])
    zusammen_ok = True
except Exception:  # noqa: BLE001 – als FAIL melden, nicht abbrechen
    zusammen_ok = False
check("Positivkontrolle: das naechste Paar laesst sich zusammenfuehren", zusammen_ok)
st5 = wg.pruefliste_stand(10, starten=gestartet.append)
check("zusammengefuehrt: Paar mit verschwundenem Begriff faellt heraus",
      all(zweites["quelle"]["id"] not in (x["quelle"]["id"], x["ziel"]["id"]) for x in st5["paare"]), st5["paare"][:2])

section("5. Seitenroute und Rechte")
MAIN = ast.parse((ROOT / "backend/main.py").read_text(encoding="utf-8"))
pl_route = next((f for f in ast.walk(MAIN) if isinstance(f, ast.AsyncFunctionDef) and f.name == "wissensgraph_pruefliste"), None)
pl_aufrufe = [ast.unparse(c.args[0]) for c in ast.walk(pl_route) if isinstance(c, ast.Call)
              and ast.unparse(c.func) == "asyncio.to_thread" and c.args] if pl_route else []
check("Pruefliste-Route liefert den gepufferten Stand (rechnet nicht im Request)",
      pl_aufrufe == ["wg.pruefliste_stand"], pl_aufrufe)

seite = next((f for f in ast.walk(MAIN) if isinstance(f, ast.AsyncFunctionDef) and f.name == "wissensgraph_seite"), None)
check("Route /wissensgraph liefert die Seite",
      seite is not None and "wissensgraph.html" in ast.unparse(seite)
      and any("'/wissensgraph'" in ast.unparse(d) for d in seite.decorator_list))
check("die Seite existiert", (ROOT / "frontend/wissensgraph.html").is_file())
# BSI M10 (deny-by-default): ohne Eintrag als Seitenrahmen verlangt die
# Middleware schon fuer die leere HTML-Huelle eine Anmeldung – live auf DEV
# gesehen (401), waehrend /feedback & Co. 200 liefern.
try:
    from backend import zugang_regel as zr
    eintrag = zr.AUSNAHMEN.get(("GET", "/wissensgraph"))
except Exception as e:  # noqa: BLE001
    eintrag = f"nicht lesbar: {e}"
check("Seitenrahmen in der Zugangsregel (BSI M10) eingetragen",
      isinstance(eintrag, tuple) and eintrag[0] == "seite", eintrag)
check("keine /api/wissensgraph/-Route als Ausnahme (Daten bleiben angemeldet)",
      not any(str(k[1]).startswith("/api/wissensgraph") for k in zr.AUSNAHMEN) if isinstance(eintrag, tuple) else False)
routen = []
for f in ast.walk(MAIN):
    if isinstance(f, ast.AsyncFunctionDef):
        for dek in f.decorator_list:
            if isinstance(dek, ast.Call) and dek.args and isinstance(dek.args[0], ast.Constant) \
                    and str(dek.args[0].value).startswith("/api/wissensgraph/"):
                deps = {ast.unparse(x) for x in ast.walk(f.args) if isinstance(x, ast.Call)}
                routen.append((dek.args[0].value, deps))
# Seit 2026-10-31 drei Stufen (Steuerung Admin, Inhalte Wissenseditoren je
# Gruppe, Pflege globale Wissenseditoren) – die genaue Zuordnung je Route steht
# in test_endpoint_rights, die Filterwirkung in test_wissensgraph_rechte. Hier
# die Regel: KEINE Daten-Route haengt an einer schwaecheren Schranke.
STARK = ("require_local_auth", "require_wissensgraph_leser", "require_knowledge_editor")
check("Positivkontrolle: Daten-Routen gefunden", len(routen) >= 19, len(routen))
schwach = [r for r, d in routen if r != "/api/wissensgraph/zugang" and not any(s in x for x in d for s in STARK)]
check("JEDE /api/wissensgraph/-Daten-Route an einer der drei Schranken", not schwach, schwach)

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
