#!/usr/bin/env python3
"""Wissensgraph: Rechenlast je Nachlauf-Schritt (ECHT 2026-11-09).

Gemessen auf ECHT: ein Schritt der Widerspruchspruefung kostete ~3,5 s CPU –
bei einem Schritt alle ~3 s also ein dauerhaft voller Kern. Die Posten:
``quellen_index()`` las alle 13.247 Quelldateien (1,1 s), ``json.dump`` der
17-MB-``widersprueche.json`` lief ueber den Python-Encoder (1,3 s),
``im_umfang`` fiel 211.000-mal (0,65 s), die Ablage wurde zweimal geparst.

Geprueft wird die WIRKUNG, nicht das Vorkommen:
  1. ``_json_schreiben`` schreibt byte-gleich zu ``json.dumps`` und kommt
     OHNE den Python-Encoder aus (eine Falle darin wirft, mit
     Positivkontrolle, dass sie ``json.dump`` wirklich faengt); der Speicher
     haengt am groessten Element, nicht an der ganzen Datei.
  2. ``quellen_index()`` liest beim zweiten Aufruf KEINE Datei, sieht aber
     jede Aenderung: eigene, fremde (``os.replace``), einen ausgetauschten
     Ordner gleicher mtime; ein frisch geaenderter Ordner wird nie gecacht;
     die Rueckgabe ist eine Kopie.
  3. ``im_umfang_menge`` ist dieselbe Regel wie ``im_umfang`` je Element
     (mit dem ECHTEN ``knowledge_groups`` gegen ein Sandkasten-Manifest), und
     beide ``offene_begriffe`` liefern dasselbe wie die alte Fassung – mit
     EINEM Gruppenfilter-Aufruf statt einem je Knoten und Quelle.
  4. ``_vermerken`` parst die Ablage einmal und markiert den Graphen genau
     dann als veraltet, wenn sich seine Widerspruchskanten aendern.

    python3 tests/test_wissensgraph_nachlauf_last.py
"""
import io
import json
import os
import sys
import tempfile
import time
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


def abbruch(grund):
    print(f"ABBRUCH – {grund}")
    sys.exit(2)


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
    from backend import atomar
    from backend import knowledge_groups as kg
    from backend import wissensgraph as wg
    from backend import wissensgraph_extraktion as wgx
    from backend import wissensgraph_widerspruch as ww
    from backend import wissensgraph_wiki as wiki
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht importierbar: {e}")

for name in ("_json_teile", "im_umfang_menge"):
    if not hasattr(wg if name == "_json_teile" else wgx, name):
        abbruch(f"{name} fehlt – Altstand, nicht pruefbar")

TMP = Path(tempfile.mkdtemp(prefix="wg_last_"))
wg.ORDNER = TMP / "graph"
kg.MANIFEST_PATH = TMP / "groups.json"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)) or not str(kg.MANIFEST_PATH).startswith(str(TMP)):
    abbruch("Sandkasten greift nicht")

QD = wg._o() / "quellen"


def ent(n, typ="system"):
    return {"name": n, "typ": typ, "beschreibung": ""}


A, B, C, D = (f"data/rag/t/{x}.md" for x in ("a", "b", "c", "d"))
FUELL = [f"data/rag/t/f{i}.md" for i in range(12)]


def bestand():
    wg.quelle_schreiben(A, 1.0, [ent("Reisekosten", "prozess"), ent("SAP")], [])
    wg.quelle_schreiben(B, 1.0, [ent("Reisekosten", "prozess"), ent("SAP"), ent("Kasse")], [])
    wg.quelle_schreiben(C, 1.0, [ent("Reisekosten", "prozess"), ent("Kasse")], [])
    wg.quelle_schreiben(D, 1.0, [ent("SAP"), ent("Kasse")], [])
    for i, m in enumerate(FUELL):
        wg.quelle_schreiben(m, 1.0, [ent(f"Z{i}", "ort"), ent(f"Z{(i + 1) % 12}", "ort")], [])
    wg._zuruecksetzen_fuer_test()


def ordner_alt(sek=60):
    """Ordner-mtime in die Vergangenheit – erst dann darf gecacht werden."""
    t = time.time() - sek
    os.utime(QD, (t, t))


bestand()
atomar.schreiben(kg.MANIFEST_PATH, {
    "groups": [{"id": "g1", "name": "G1"}, {"id": "g2", "name": "G2"}],
    "assignments": {A: ["g1"], B: ["g1", "g2"], C: ["g2"], FUELL[0]: ["g1"], FUELL[1]: ["g2"]}})

# ─── Positivkontrollen ──────────────────────────────────────────────────────
section("0. Positivkontrollen")
idx0 = wg.quellen_index()
mehr = [k for k in wg.graph()["knoten"] if k["typ"] != wg.TYP_QUELLE and len(k["sources"]) >= 2]
check("Sandkasten-Bestand: 16 Quellen im Index", len(idx0) == 16, f"{len(idx0)}")
check("mehrfach belegte Begriffe vorhanden (sonst waeren die Listen trivial leer)", len(mehr) >= 10, f"{len(mehr)}")
check("echtes knowledge_groups liest das Sandkasten-Manifest",
      kg.filter_paths_by_groups([A, C, D], ["g1"]) == [A]
      and kg.filter_paths_by_groups([A, C, D], ["ungrouped"]) == [D],
      f"{kg.filter_paths_by_groups([A, C, D], ['g1'])}")
if _fail:
    abbruch("Positivkontrollen fehlgeschlagen – Inhaltspruefungen waeren nicht deutbar")

# ─── 1. Schreiben ───────────────────────────────────────────────────────────
section("1. _json_schreiben: C-Encoder, byte-gleich, Speicher je Block")
FIXTURES = [
    {}, [], "x", 1, 1.5, None, True, float("nan"),
    {"a": {}, "b": [], "c": [{}], "d": {"e": []}},
    {"ä": "–€😀", "n": [1, 2.5, None, True, False, "x\n\"y\\"], "t": (1, 2)},
    {1: "int-schluessel", None: "n", True: "b", 2.5: "f"},
    {"geprueft": {"k:a": {"quellen": {A: 1.0}, "zeit": 3.0}, "k:b": {"quellen": {}, "fehler": "x"}},
     "befunde": [{"a": A, "b": B}, {"x": [[{"tief": {"tiefer": 1}}]]}]},
    [[1, [2, [3, {"z": []}]]], {"k": {"l": {"m": "n"}}}],
]
# Grosse Behaelter, damit die Block-Zweige (Liste UND dict) ueberhaupt laufen
FIXTURES += [list(range(7)), {f"k{i}": [i, {"x": i}] for i in range(7)},
             {"l": [{"a": i} for i in range(5)], "d": {f"k{i}": i for i in range(5)}, "s": "x"},
             {"t": tuple(range(5)), "nk": {1: "a", 2: "b", 3: "c", 4: "d"}}]
for i, f in enumerate(FIXTURES):
    soll = json.dumps(f, ensure_ascii=False)
    abw = [(t, b) for t in (0, 1, 2) for b in (1, 2, 3, 1000)
           if "".join(wg._json_teile(f, tiefe=t, block=b)) != soll]
    ist = "".join(wg._json_teile(f))
    check(f"Fixture {i}: identisch zu json.dumps (Vorgabe und alle tiefe/block)", ist == soll and not abw,
          f"{ist[:80]!r} gegen {soll[:80]!r}, abweichend bei {abw[:4]}")

_orig = json.encoder._make_iterencode


def _falle(*a, **k):
    raise RuntimeError("Python-Encoder benutzt")


json.encoder._make_iterencode = _falle
try:
    try:
        json.dump({"a": [1]}, io.StringIO(), ensure_ascii=False)
        gefangen = False
    except RuntimeError:
        gefangen = True
    check("Positivkontrolle: die Falle faengt json.dump", gefangen)
    ziel = TMP / "probe.json"
    gross = FIXTURES[11]
    try:
        wg._json_schreiben(ziel, gross)
        geschrieben, grund = True, ""
    except RuntimeError as e:
        geschrieben, grund = False, str(e)
    check("_json_schreiben kommt ohne Python-Encoder aus", geschrieben, grund)
finally:
    json.encoder._make_iterencode = _orig
check("Datei byte-gleich zu json.dumps",
      ziel.is_file() and ziel.read_text(encoding="utf-8") == json.dumps(gross, ensure_ascii=False))
check("keine Temp-Datei liegen geblieben", not list(TMP.glob("probe.json.*.tmp")))

graphartig = {"version": 1, "erzeugt": 1.0, "quellen": 3,
              "knoten": [{"id": f"k:{i}", "name": f"Name {i}", "sources": [A, B]} for i in range(3000)],
              "kanten": [{"von": f"k:{i}", "nach": f"k:{i + 1}", "art": "x"} for i in range(3000)],
              "geprueft": {f"k:{i}": {"quellen": {A: 1.0, B: 2.0}, "zeit": 1.0} for i in range(3000)}}
teile = list(wg._json_teile(graphartig, block=60))
gesamt = sum(len(t) for t in teile)
groesstes = max(len(t) for t in teile)
check("Speicher haengt an einem Block (groesstes Stueck < 2 % der Datei bei 60 von 9000 Elementen)",
      groesstes * 50 < gesamt, f"groesstes {groesstes} von {gesamt} Zeichen")
check("je Block EIN Stueck, nicht je Element (weniger als 300 Stuecke)", len(teile) < 300, f"{len(teile)}")
check("graphartige Daten ebenfalls identisch", "".join(teile) == json.dumps(graphartig, ensure_ascii=False))
check("Vorgabe-Block (1000) bleibt identisch",
      "".join(wg._json_teile(graphartig)) == json.dumps(graphartig, ensure_ascii=False))

# ─── 2. quellen_index ───────────────────────────────────────────────────────
section("2. quellen_index: gecacht am Ordnerstand, sieht jede Aenderung")
_lesen_orig = wg._json_lesen
gelesen = {"n": 0}


def _zaehlend(p, vorgabe):
    if Path(p).parent == QD:
        gelesen["n"] += 1
    return _lesen_orig(p, vorgabe)


wg._json_lesen = _zaehlend


def index_mit_zaehlung():
    gelesen["n"] = 0
    return wg.quellen_index(), gelesen["n"]


try:
    # Eine nicht erlaubte Datei im Ordner: der Index bleibt bei der Isolationsregel.
    (QD / "fremd.json").write_text(json.dumps({"pfad": "etc/passwd", "mtime": 1.0}), encoding="utf-8")
    ordner_alt()
    wg._zuruecksetzen_fuer_test()
    i1, n1 = index_mit_zaehlung()
    i2, n2 = index_mit_zaehlung()
    check("erster Aufruf liest alle Quelldateien", n1 >= 16, f"{n1}")
    check("zweiter Aufruf liest KEINE Datei", n2 == 0, f"{n2} gelesen")
    check("zweiter Aufruf liefert denselben Index", i1 == i2)
    check("nicht erlaubter Pfad bleibt draussen", "etc/passwd" not in i1 and len(i1) == 16, f"{len(i1)}")

    i2["data/rag/t/erfunden.md"] = 9.0
    i2[A] = 99.0
    i3, _n = index_mit_zaehlung()
    check("Rueckgabe ist eine Kopie (Aenderung schlaegt nicht durch)",
          "data/rag/t/erfunden.md" not in i3 and i3.get(A) == 1.0, f"{i3.get(A)}")

    X = "data/rag/t/x.md"
    wg.quelle_schreiben(X, 5.0, [ent("Neu")], [])
    i4, n4 = index_mit_zaehlung()
    check("eigene Aenderung sofort sichtbar", i4.get(X) == 5.0, f"{i4.get(X)}")

    ordner_alt()
    index_mit_zaehlung()
    _i, n5 = index_mit_zaehlung()
    check("danach wieder gecacht", n5 == 0, f"{n5}")

    # Fremder Prozess: atomar ersetzt, ohne die Funktionen des Moduls
    pa = wg._quell_datei(A)
    roh = json.loads(pa.read_text(encoding="utf-8"))
    roh["mtime"] = 7.0
    tmp = pa.with_name(pa.name + ".fremd.tmp")
    tmp.write_text(json.dumps(roh), encoding="utf-8")
    os.replace(tmp, pa)
    i6, _n = index_mit_zaehlung()
    check("fremde Aenderung (os.replace) sichtbar", i6.get(A) == 7.0, f"{i6.get(A)}")

    # Frisch geaenderter Ordner: nie cachen (grobe Zeitstempel, siehe Docstring)
    os.utime(QD, None)
    _a, na = index_mit_zaehlung()
    _b, nb = index_mit_zaehlung()
    check("frisch geaenderter Ordner wird nicht gecacht (beide Aufrufe lesen)", na > 0 and nb > 0, f"{na}/{nb}")

    # Ausgetauschter Ordner mit GLEICHER mtime – nur die Inode unterscheidet ihn
    ordner_alt(120)
    st = QD.stat()
    index_mit_zaehlung()
    _c, nc = index_mit_zaehlung()
    neu = QD.with_name("quellen.neu")
    neu.mkdir()
    for p in QD.glob("*.json"):
        q = json.loads(p.read_text(encoding="utf-8"))
        if q.get("pfad") == B:
            q["mtime"] = 42.0
        (neu / p.name).write_text(json.dumps(q), encoding="utf-8")
    QD.rename(QD.with_name("quellen.alt"))
    neu.rename(QD)
    os.utime(QD, ns=(st.st_atime_ns, st.st_mtime_ns))
    gleich = QD.stat().st_mtime_ns == st.st_mtime_ns
    i7, _n = index_mit_zaehlung()
    check("Messaufbau: Cache stand, neuer Ordner hat dieselbe mtime", nc == 0 and gleich, f"{nc}, {gleich}")
    check("ausgetauschter Ordner wird erkannt (Inode)", i7.get(B) == 42.0, f"{i7.get(B)}")
finally:
    wg._json_lesen = _lesen_orig

# ─── 3. Umfang als Menge ────────────────────────────────────────────────────
section("3. im_umfang_menge und offene_begriffe")
wg._zuruecksetzen_fuer_test()
for p in QD.glob("*.json"):            # Bestand zuruecksetzen (alle mtimes 1.0, ohne Fremdes)
    p.unlink()
bestand()
MENGE = [A, B, C, D, A, "etc/passwd", "data/rag/../x.md", *FUELL]
for gr in ([], ["g1"], ["g2"], ["ungrouped"], ["g1", "g2"], ["unbekannt"]):
    soll = {m for m in MENGE if wgx.im_umfang(m, gr)}
    ist = wgx.im_umfang_menge(MENGE, gr)
    check(f"gruppen={gr}: dieselbe Menge wie im_umfang je Element", ist == soll, f"{sorted(ist)} gegen {sorted(soll)}")


def ww_alt(gruppen=None):
    """Die Fassung vor 2026-11-09, wortgleich bis auf die Umfangspruefung."""
    g = wg.graph()
    stand = wg.quellen_index()
    grenze = ww._grenze(g["quellen"])
    geprueft = wg.widersprueche_lesen()["geprueft"]
    raus = []
    for k in g["knoten"]:
        if k["typ"] == wg.TYP_QUELLE:
            continue
        q = {m: stand[m] for m in k["sources"] if m in stand and wgx.im_umfang(m, gruppen or [])}
        if not 2 <= len(q) <= grenze:
            continue
        alt = geprueft.get(k["id"]) or {}
        if alt.get("quellen") == q and (not alt.get("fehler") or int(alt.get("versuche") or 0) >= ww.MAX_VERSUCHE):
            continue
        raus.append((k["id"], q))
    raus.sort(key=lambda x: (-len(x[1]), x[0]))
    return raus


def wiki_alt(gruppen=None):
    g = wg.graph()
    stand = wg.quellen_index()
    grenze = max(3, wg.HUB_ANTEIL * g["quellen"])
    wi = wg.wiki_index_lesen()
    raus = []
    for k in g["knoten"]:
        if k["typ"] == wg.TYP_QUELLE:
            continue
        q = {m: stand[m] for m in k["sources"] if m in stand}
        im = [m for m in q if wgx.im_umfang(m, gruppen or [])]
        if not 2 <= len(im) <= grenze:
            continue
        alt = wi.get(k["id"]) or {}
        if alt.get("datei") and alt.get("quellen") == q:
            continue
        if alt.get("fehler_quellen") == q and int(alt.get("versuche") or 0) >= wiki.MAX_VERSUCHE:
            continue
        raus.append((k["id"], q))
    raus.sort(key=lambda x: (-len(x[1]), x[0]))
    return raus


# Ein geprufter Begriff, damit auch der Ueberspringen-Zweig mitlaeuft
erste = ww.offene_begriffe(None)
if erste:
    ww._vermerken(erste[0][0], erste[0][1], [])
for gr in (None, ["g1"], ["g2"], ["ungrouped"]):
    a_ww, a_wiki = ww_alt(gr), wiki_alt(gr)
    check(f"Widerspruch, gruppen={gr}: wie die alte Fassung ({len(a_ww)} offen)",
          ww.offene_begriffe(gr) == a_ww)
    check(f"Wiki, gruppen={gr}: wie die alte Fassung ({len(a_wiki)} offen)",
          wiki.offene_begriffe(gr) == a_wiki)
check("Vergleich nicht trivial (mit und ohne Gruppen jeweils Begriffe offen)",
      len(ww_alt(None)) >= 3 and len(ww_alt(["g1"])) >= 1 and len(wiki_alt(None)) >= 3)

_filter_orig = kg.filter_paths_by_groups
aufrufe = {"n": 0}


def _filter_zaehlend(*a, **k):
    aufrufe["n"] += 1
    return _filter_orig(*a, **k)


kg.filter_paths_by_groups = _filter_zaehlend
try:
    aufrufe["n"] = 0
    ww.offene_begriffe(["g1"])
    n_ww = aufrufe["n"]
    aufrufe["n"] = 0
    wiki.offene_begriffe(["g1"])
    n_wiki = aufrufe["n"]
finally:
    kg.filter_paths_by_groups = _filter_orig
check("Widerspruch: EIN Gruppenfilter-Aufruf je Liste", n_ww == 1, f"{n_ww}")
check("Wiki: EIN Gruppenfilter-Aufruf je Liste", n_wiki == 1, f"{n_wiki}")

# ─── 4. _vermerken ──────────────────────────────────────────────────────────
section("4. _vermerken: einmal parsen, invalidieren nur bei Kantenaenderung")
wg._zuruecksetzen_fuer_test()
stand = wg.quellen_index()
kid = next(k["id"] for k in wg.graph()["knoten"] if k["name"] == "Reisekosten")
q = {m: stand[m] for m in (A, B, C)}
WP = wg._o() / "widersprueche.json"
_lesen_orig = wg._json_lesen
w_gelesen = {"n": 0}


def _zaehlend_w(p, vorgabe):
    if Path(p) == WP:
        w_gelesen["n"] += 1
    return _lesen_orig(p, vorgabe)


def veraltet_nach(fn):
    wg.graph()                                    # Cache frisch, nicht veraltet
    w_gelesen["n"] = 0
    fn()
    return wg._graph_veraltet, w_gelesen["n"]


befund = {"id": "x1", "kid": kid, "name": "Reisekosten", "a": A, "b": B, "mtime_a": 1.0, "mtime_b": 1.0,
          "aussage_a": "a", "aussage_b": "b", "frage": "f", "erklaerung": "e", "zeit": 1.0}
wg._json_lesen = _zaehlend_w
try:
    v0, n0 = veraltet_nach(lambda: ww._vermerken(kid, q, []))
    v1, n1 = veraltet_nach(lambda: ww._vermerken(kid, q, [befund]))
    v2, n2 = veraltet_nach(lambda: ww._vermerken(kid, q, None, "Fehler"))
    v3, n3 = veraltet_nach(lambda: ww._vermerken(kid, q, [dict(befund, zeit=2.0)]))
    v4, n4 = veraltet_nach(lambda: ww._vermerken(kid, q, []))
finally:
    wg._json_lesen = _lesen_orig
check("ohne Befund und ohne vorhandene: Graph bleibt gueltig", v0 is False)
check("neuer Befund: Graph veraltet", v1 is True)
check("Fehlversuch (Befunde unveraendert): Graph bleibt gueltig", v2 is False)
check("gleiche Kante, anderer Zeitstempel: Graph bleibt gueltig", v3 is False)
check("Befund entfernt: Graph veraltet", v4 is True)
check("je _vermerken wird die Ablage genau EINMAL geparst", (n0, n1, n2, n3, n4) == (1,) * 5,
      f"{(n0, n1, n2, n3, n4)}")
check("Ablage danach ohne Befund, Begriff geprueft",
      wg.widersprueche_lesen()["befunde"] == [] and kid in wg.widersprueche_lesen()["geprueft"])
ww._vermerken(kid, q, [befund])
v5, _n = veraltet_nach(lambda: wg.widersprueche_schreiben({"geprueft": {}, "befunde": []}))
check("ohne vorher_befunde liest widersprueche_schreiben selbst (Befund weg → veraltet)", v5 is True)

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
