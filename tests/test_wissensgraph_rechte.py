#!/usr/bin/env python3
"""Wissensgraph: Rechte nach Wissensrollen (Festlegung des Betreibers 2026-10-31).

  * globale Wissenseditoren sehen ALLES und pflegen,
  * Editoren einzelner Wissensgruppen sehen NUR, was ihre Dokumente hergeben,
  * Administratoren ALLEIN steuern (Schalter, Aufbau), sehen aber keine Inhalte,
  * normale Benutzer: nichts.

Gemessen wird die WIRKUNG, nicht das Vorkommen:
  1. Rechte-Matrix: ``_wissensgraph_zugang``/``_wissensgraph_erlaubt`` werden
     AUS main.py herausgeloest und mit Attrappen der Praedikate ausgefuehrt.
  2. Teilgraph eines Gruppen-Editors: kein Pfad, kein Begriff, kein
     Beschreibungstext, keine Kante und kein Widerspruch aus einer fremden
     Gruppe – geprueft am serialisierten Ergebnis von Ansicht und Detail.
  3. Widersprueche und Wiki-Seiten: sichtbar nur, wenn ALLE beteiligten
     Dokumente in den eigenen Gruppen liegen.
  4. Jede Inhalts-Route in main.py holt sich den Ausschnitt des Fragenden
     (am Syntaxbaum: der Rumpf ruft ``_wg_teilgraph_fuer`` bzw.
     ``_wissensgraph_erlaubt`` und reicht das Ergebnis weiter).

    python3 tests/test_wissensgraph_rechte.py
"""
import ast
import json
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

    def __init__(self):
        self.s = {}

    def get_setting(self, k, d=None):
        return self.s.get(k, d)

    def save_setting(self, k, v):
        self.s[k] = v

    def get_skill_states(self):
        return {}

    def __getattr__(self, n):
        return None


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
sys.modules["backend.config"] = _cfgmod

try:
    from backend import wissensgraph as wg
    from backend import wissensgraph_widerspruch as ww
    from backend import wissensgraph_wiki as wiki
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)
for n in ("teilgraph",):
    if not hasattr(wg, n):
        print(f"ABBRUCH – wissensgraph.{n} fehlt")
        sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="wg_rechte_"))
wg.ORDNER = TMP / "graph"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)

MAIN = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
FUNKTIONEN = {f.name: f for f in ast.walk(MAIN) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}


# ─── 1. Rechte-Matrix ────────────────────────────────────────────────────────

section("1. Rechte-Matrix (Funktionen aus main.py, Praedikate als Attrappen)")
fehlend = [n for n in ("_wissensgraph_zugang", "_wissensgraph_erlaubt") if n not in FUNKTIONEN]
if fehlend:
    print(f"ABBRUCH – in main.py fehlt {fehlend}")
    sys.exit(2)
ROLLEN = {
    "glob": {"global": True, "gruppen": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}], "admin": False},
    "ga": {"global": False, "gruppen": [{"id": "a", "name": "A"}], "admin": False},
    "admin": {"global": False, "gruppen": [], "admin": True},
    "admin_glob": {"global": True, "gruppen": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}], "admin": True},
    "normal": {"global": False, "gruppen": [], "admin": False},
    "kaputt": {"global": False, "gruppen": None, "admin": False},
}


def _editable(u):
    if ROLLEN[u]["gruppen"] is None:
        raise RuntimeError("Index nicht lesbar")
    return ROLLEN[u]["gruppen"]


kg_stub = types.ModuleType("backend.knowledge_groups")
kg_stub.filter_paths_by_groups = lambda pfade, gids: [p for p in pfade if p.split("/")[2] in gids]
AUFRUFE = {"n": 0}


def _editable_gezaehlt(u):
    AUFRUFE["n"] += 1
    return _editable(u)


ns = {"_may_edit_knowledge": lambda u: ROLLEN[u]["global"], "_editable_groups_for": _editable_gezaehlt,
      "_is_admin_user": lambda u: ROLLEN[u]["admin"], "time": __import__("time"), "_wg_zugang_cache": {}}
# Die Haltezeit aus main.py selbst, nicht abgetippt.
ttl = next((n.value for n in MAIN.body if isinstance(n, (ast.Assign, ast.AnnAssign))
            and "_WG_ZUGANG_TTL" in ast.unparse(n)), None)
if ttl is None:
    print("ABBRUCH – _WG_ZUGANG_TTL fehlt in main.py")
    sys.exit(2)
ns["_WG_ZUGANG_TTL"] = ast.literal_eval(ttl)
_alt_kg = sys.modules.get("backend.knowledge_groups")
sys.modules["backend.knowledge_groups"] = kg_stub
for n in ("_wissensgraph_zugang", "_wissensgraph_erlaubt"):
    exec(compile(ast.Module(body=[FUNKTIONEN[n]], type_ignores=[]), "main.py", "exec"), ns)

A1, A2, B1 = "data/rag/a/1.md", "data/rag/a/2.md", "data/rag/b/1.md"


def ent(n, typ="system", b=""):
    return {"name": n, "typ": typ, "beschreibung": b}


wg.quelle_schreiben(A1, 1.0, [ent("Server", b="Server laut A."), ent("Router"), ent("Drucker")],
                    [{"von": "Server", "nach": "Router", "art": "nutzt"}])
wg.quelle_schreiben(A2, 1.0, [ent("Server", b="Kurz."), ent("Router")], [])
wg.quelle_schreiben(B1, 1.0, [ent("Server", b="GEHEIM: viel laengere Beschreibung des Servers aus der fremden Gruppe."),
                              ent("Geheimprojekt", "konzept", "GEHEIM: Projekt nur in Gruppe B"), ent("Drucker")],
                    [{"von": "Server", "nach": "Drucker", "art": "druckt_ueber"},
                     {"von": "Geheimprojekt", "nach": "Server", "art": "nutzt"}])
wg._zuruecksetzen_fuer_test()

z = {u: ns["_wissensgraph_zugang"](u) for u in ROLLEN}
e = {u: ns["_wissensgraph_erlaubt"](u) for u in ROLLEN}
check("globaler Wissenseditor: alles, pflegt, steuert nicht", z["glob"]["stufe"] == "global" and z["glob"]["pflegen"]
      and not z["glob"]["steuern"] and e["glob"] is None, (z["glob"], e["glob"]))
check("Gruppen-Editor: nur seine Dokumente, pflegt nicht", z["ga"]["stufe"] == "gruppen" and not z["ga"]["pflegen"]
      and e["ga"] == {A1, A2}, (z["ga"], e["ga"]))
check("Admin ALLEIN: steuert, sieht KEINE Inhalte, pflegt nicht", z["admin"]["stufe"] == "keine"
      and z["admin"]["steuern"] and not z["admin"]["pflegen"] and e["admin"] == set(), (z["admin"], e["admin"]))
check("Admin und globaler Wissenseditor: alles", z["admin_glob"]["stufe"] == "global" and z["admin_glob"]["steuern"]
      and z["admin_glob"]["pflegen"] and e["admin_glob"] is None)
check("normaler Benutzer: nichts", z["normal"]["stufe"] == "keine" and not z["normal"]["steuern"]
      and not z["normal"]["pflegen"] and e["normal"] == set())
check("Fehler beim Ermitteln der Gruppen: kein Zugang (fail-closed)", z["kaputt"]["stufe"] == "keine"
      and e["kaputt"] == set(), z["kaputt"])
vorher = AUFRUFE["n"]
z2 = ns["_wissensgraph_zugang"]("ga")
check("Zwischenspeicher: zweite Frage binnen der Haltezeit rechnet NICHT neu", AUFRUFE["n"] == vorher, AUFRUFE["n"] - vorher)
z2["gruppen"].append({"id": "b", "name": "B"})
z2["stufe"] = "global"
check("Zwischenspeicher: Aenderung am Ergebnis aendert den Speicher nicht",
      ns["_wissensgraph_zugang"]("ga")["stufe"] == "gruppen" and len(ns["_wissensgraph_zugang"]("ga")["gruppen"]) == 1)
check("Haltezeit kurz (hoechstens 60 s – Rechteaenderungen wirken sonst zu spaet)",
      0 < ns["_WG_ZUGANG_TTL"] <= 60, ns["_WG_ZUGANG_TTL"])
ns["_wg_zugang_cache"]["ga"] = (ns["_wg_zugang_cache"]["ga"][0] - ns["_WG_ZUGANG_TTL"] - 1, ns["_wg_zugang_cache"]["ga"][1])
ns["_wissensgraph_zugang"]("ga")
check("nach Ablauf der Haltezeit wird neu gerechnet", AUFRUFE["n"] == vorher + 1, AUFRUFE["n"] - vorher)
if _alt_kg is not None:
    sys.modules["backend.knowledge_groups"] = _alt_kg

# ─── 1b. Portal-Kachel ───────────────────────────────────────────────────────

section("1b. Portal-Kachel: nur wenn es etwas zu sehen gibt (Vergleichsbericht 2026-11-01)")
if "_wissensgraph_kachel" not in FUNKTIONEN:
    check("_wissensgraph_kachel steht in main.py", False)
else:
    from backend import wissensgraph_extraktion as wgx
    exec(compile(ast.Module(body=[FUNKTIONEN["_wissensgraph_kachel"]], type_ignores=[]), "main.py", "exec"), ns)
    kachel = ns["_wissensgraph_kachel"]
    _alt_einst, _alt_inhalt, _alt_ordner = wgx.einstellungen, wg.hat_inhalt, wg.ORDNER
    check("Positivkontrolle: der Sandkasten-Graph hat Inhalt", wg.hat_inhalt() is True)
    wgx.einstellungen = lambda frisch=False: dict(wgx.VORGABEN, aktiv=False)
    check("Graph aus, Bestand da: Gruppen-Editor sieht die Kachel", kachel("ga", False) is True)
    wg.ORDNER = TMP / "gibt_es_nicht"
    check("kein Graph-Ordner: kein Inhalt", wg.hat_inhalt() is False)
    # Ein VORHANDENER, leerer Quellen-Ordner – sonst bricht scandir ab und die
    # Pruefung waere unabhaengig vom Code wahr (Gegenprobe war stumm).
    (TMP / "leer" / "quellen").mkdir(parents=True)
    (TMP / "leer" / "quellen" / "notiz.txt").write_text("x", encoding="utf-8")
    wg.ORDNER = TMP / "leer"
    check("Positivkontrolle: leerer Quellen-Ordner (nur Fremddatei) hat keinen Inhalt", wg.hat_inhalt() is False)
    check("Graph aus, kein Bestand: Gruppen-Editor sieht KEINE Kachel", kachel("ga", False) is False)
    check("Graph aus, kein Bestand: globaler Editor sieht KEINE Kachel", kachel("glob", False) is False)
    check("Graph aus, kein Bestand: Admin sieht sie (er schaltet ein)", kachel("admin", True) is True)
    wgx.einstellungen = lambda frisch=False: dict(wgx.VORGABEN, aktiv=True)
    check("Graph an, noch kein Bestand: Gruppen-Editor sieht die Kachel", kachel("ga", False) is True)
    check("normaler Benutzer: nie", kachel("normal", False) is False)

    def _wirft(*_a, **_k):
        raise RuntimeError("kaputt")
    wgx.einstellungen = _wirft
    check("Fehler beim Nachsehen: keine Kachel (fail-closed)", kachel("ga", False) is False)
    wgx.einstellungen, wg.hat_inhalt, wg.ORDNER = _alt_einst, _alt_inhalt, _alt_ordner
    me = [n for n in ast.walk(MAIN) if isinstance(n, ast.Dict)
          and any(isinstance(k, ast.Constant) and k.value == "wissensgraph" for k in n.keys)]
    werte = [ast.unparse(v) for d in me for k, v in zip(d.keys, d.values)
             if isinstance(k, ast.Constant) and k.value == "wissensgraph"]
    check("/api/me: das Recht \"wissensgraph\" kommt aus _wissensgraph_kachel",
          bool(werte) and all(w.startswith("_wissensgraph_kachel(") for w in werte), werte)

# ─── 2. Teilgraph ────────────────────────────────────────────────────────────

section("2. Teilgraph eines Gruppen-Editors")
voll = wg.teilgraph(None)
teil = wg.teilgraph({A1, A2})
ids_voll = {k["id"] for k in voll["knoten"]}
check("Positivkontrolle: der Gesamtgraph kennt das Geheimprojekt und die B-Beschreibung",
      "e:geheimprojekt" in ids_voll and "GEHEIM" in json.dumps(voll, ensure_ascii=False))
check("ohne Einschraenkung: der Gesamtgraph selbst", voll is wg.graph())
ids = {k["id"] for k in teil["knoten"]}
check("Begriff nur aus fremder Gruppe fehlt", "e:geheimprojekt" not in ids, sorted(ids))
check("gemeinsamer Begriff bleibt", "e:server" in ids)
srv = next((k for k in teil["knoten"] if k["id"] == "e:server"), {})
check("Quellen nur aus den eigenen Gruppen", srv.get("sources") == [A1, A2], srv.get("sources"))
check("Beschreibung aus EIGENER Quelle, nicht die laengere fremde", srv.get("zusammenfassung") == "Server laut A.",
      srv.get("zusammenfassung"))
kanten = {(k["von"], k["nach"], k["art"]) for k in teil["knoten"] and teil["kanten"]}
check("Kante, die nur ein fremdes Dokument belegt, fehlt",
      not any(a == "druckt_ueber" for _v, _n, a in kanten), sorted(kanten))
check("eigene Kante bleibt", any(a == "nutzt" and {v, n} == {"e:server", "e:router"} for v, n, a in kanten))
a_v = wg.ansicht(g=teil)
d_v = wg.knoten_detail("e:server", teil)
roh = json.dumps([a_v, d_v], ensure_ascii=False)
check("Ansicht und Detail: kein fremder Pfad, kein fremder Text",
      "data/rag/b/" not in roh and "GEHEIM" not in roh and "Geheimprojekt" not in roh,
      [x for x in ("data/rag/b/", "GEHEIM", "Geheimprojekt") if x in roh])
check("Detail eines fremden Begriffs: nicht vorhanden", wg.knoten_detail("e:geheimprojekt", teil) is None)
check("gleicher Ausschnitt: aus dem Speicher", wg.teilgraph({A2, A1}) is teil)
wg.quelle_schreiben(A2, 2.0, [ent("Server", b="Kurz."), ent("Router"), ent("Switch")], [])
check("geaenderte Quelle: Ausschnitt neu abgeleitet", "e:switch" in {k["id"] for k in wg.teilgraph({A1, A2})["knoten"]})

# ─── 3. Widersprueche und Wiki ───────────────────────────────────────────────

section("3. Widersprueche und Wiki-Seiten")
stand = wg.quellen_index()


def befund(a, b, bid):
    return {"id": bid, "kid": "e:server", "name": "Server", "a": a, "b": b, "mtime_a": stand[a], "mtime_b": stand[b],
            "aussage_a": "x", "aussage_b": "y", "erklaerung": "", "zeit": 1}


wg.widersprueche_schreiben({"geprueft": {}, "befunde": [befund(A1, A2, "eigen"), befund(A1, B1, "gemischt")]})
check("Positivkontrolle: global beide Befunde", {b["id"] for b in ww.liste()} == {"eigen", "gemischt"})
check("Gruppen-Editor: nur der Befund mit BEIDEN Dokumenten in seinen Gruppen",
      [b["id"] for b in ww.liste({A1, A2})] == ["eigen"], [b["id"] for b in ww.liste({A1, A2})])
tg = wg.teilgraph({A1, A2})
wk = [k for k in tg["kanten"] if k["art"] == wg.KANTE_WIDERSPRUCH]
check("Teilgraph: Widerspruchskante nur zwischen eigenen Dokumenten",
      len(wk) == 1 and {wk[0]["von"], wk[0]["nach"]} == {"q:" + A1, "q:" + A2}, wk)
wg.wiki_index_schreiben({"e:server": {"datei": "s.md", "quellen": {A1: 1.0, B1: 1.0}},
                         "e:router": {"datei": "r.md", "quellen": {A1: 1.0, A2: 2.0}}})
check("Wiki: global sichtbar", wiki.sichtbar("e:server", None))
check("Wiki: Seite aus eigenen UND fremden Quellen fuer Gruppen-Editor gesperrt", not wiki.sichtbar("e:server", {A1, A2}))
check("Wiki: Seite nur aus eigenen Quellen sichtbar", wiki.sichtbar("e:router", {A1, A2}))
check("Wiki: ohne Seite nicht sichtbar (nichts zu zeigen)", not wiki.sichtbar("e:drucker", {A1, A2}))
check("Wiki erzeugen: Begriff mit fremder Quelle gesperrt", not wiki.erzeugen_erlaubt("e:server", {A1, A2}))
check("Wiki erzeugen: Begriff nur in eigenen Quellen erlaubt", wiki.erzeugen_erlaubt("e:router", {A1, A2}))
check("Wiki erzeugen: global immer", wiki.erzeugen_erlaubt("e:server", None))

# ─── 4. Inhalts-Routen holen den Ausschnitt des Fragenden ───────────────────

section("4. Inhalts-Routen in main.py")


def dep_von(f):
    return {ast.unparse(x.args[0]) for x in ast.walk(f.args)
            if isinstance(x, ast.Call) and ast.unparse(x.func) == "Depends" and x.args}


leser = [f for f in FUNKTIONEN.values() if "require_wissensgraph_leser" in dep_von(f)]
check("Positivkontrolle: Inhalts-Routen gefunden", len(leser) >= 8, [f.name for f in leser])
for f in leser:
    rumpf = ast.unparse(f)
    if "rueckmeldung" in f.name:
        # Gerufen wird ueber asyncio.to_thread(wg.rueckmeldung…, user, …): die
        # Funktion steht als ERSTES Argument, der Benutzer muss als zweites folgen.
        aufrufe = [c for c in ast.walk(f) if isinstance(c, ast.Call) and c.args
                   and ast.unparse(c.func) == "asyncio.to_thread"
                   and ast.unparse(c.args[0]).startswith("wg.rueckmeldung")]
        check(f"{f.name}: Rueckmeldung je Benutzer (user wird uebergeben)",
              bool(aufrufe) and all(len(c.args) > 1 and ast.unparse(c.args[1]) == "user" for c in aufrufe),
              [ast.unparse(c) for c in aufrufe])
        continue
    holt = "_wg_teilgraph_fuer(" in rumpf or "_wissensgraph_erlaubt" in rumpf
    check(f"{f.name}: holt den Ausschnitt des Fragenden", holt)
helfer = FUNKTIONEN.get("_wg_teilgraph_fuer")
check("_wg_teilgraph_fuer leitet den Teilgraphen aus _wissensgraph_erlaubt ab",
      helfer is not None and "_wissensgraph_erlaubt" in ast.unparse(helfer) and "teilgraph" in ast.unparse(helfer))
for name, soll in (("wissensgraph_graph", "teil"), ("wissensgraph_knoten", "teil"),
                   ("wissensgraph_widersprueche", "erlaubt")):
    f = FUNKTIONEN.get(name)
    aufrufe = [ast.unparse(c) for c in ast.walk(f) if isinstance(c, ast.Call)
               and ast.unparse(c.func) in ("asyncio.to_thread",)] if f else []
    check(f"{name}: Ausschnitt geht in die Abfrage", any(soll in a.split(",")[-1] or f", {soll})" in a
                                                         for a in aufrufe), aufrufe)

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
