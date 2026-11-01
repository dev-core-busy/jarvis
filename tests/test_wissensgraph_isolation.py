#!/usr/bin/env python3
"""Wissensgraph: Ordner-Isolation und "inkrementell loescht nie".

Geprueft wird die EIGENSCHAFT an jedem Eintritt, nicht eine Schreibweise:
  1. ``manifest_form`` ist dieselbe Umrechnung wie ``knowledge_groups._rel``
     (Drift-Schranke: die Gruppen vergleichen gegen genau diese Form).
  2. Kein Pfad ausserhalb von ``data/rag/`` und ``/mnt/rag/`` kommt hinein –
     an JEDEM oeffentlichen Eintritt, ausgefuehrt; dazu als REGEL ueber den AST:
     jede oeffentliche Funktion mit Pfadparameter prueft (direkt oder ueber
     eine geprueft delegierende Funktion). Die Zahl der Eintritte wird genannt.
  3. Der Abgleich reiht nur erlaubte Pfade ein.
  4. Bereinigen loescht nie aus Versehen: leere Ordnerliste, abgehaengter
     Ordner, laufender Neuaufbau, leerer Index, Praefix ohne Trenner – mit den
     ECHTEN ``_nutzbare_ordner``/``_verwaiste_dateien`` aus knowledge.py und
     mindestens ZWEI Quellen je Ordner (Register: ein Element stellt den
     Loeschfall nicht her).

``backend.config`` nur als Attrappe (Register). Exit 2 = konnte nicht laufen.

    python3 tests/test_wissensgraph_isolation.py
"""
import ast
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

    def __init__(self):
        self._s = {}

    def get_setting(self, k, d=None):
        return self._s.get(k, d)

    def save_setting(self, k, v):
        self._s[k] = v

    def get_skill_states(self):
        return {}

    def __getattr__(self, n):
        return None


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
sys.modules["backend.config"] = _cfgmod

try:
    from backend import knowledge_groups as kg
    from backend import wissensgraph as wg
    from backend import wissensgraph_extraktion as wgx
    from backend.tools import knowledge as kn
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – Module nicht importierbar: {e}")
    sys.exit(2)

for name in ("manifest_form", "_erlaubt", "quelle_schreiben", "einreihen", "umbenennen",
             "praefix_umbenennen", "quellen_entfernen", "_zuruecksetzen_fuer_test"):
    if not hasattr(wg, name):
        print(f"ABBRUCH – wissensgraph.{name} fehlt")
        sys.exit(2)
if not all(hasattr(kn, n) for n in ("_nutzbare_ordner", "_verwaiste_dateien")):
    print("ABBRUCH – knowledge._nutzbare_ordner/_verwaiste_dateien fehlen")
    sys.exit(2)

REAL_ROOT = wg.PROJECT_ROOT

# ── 1. Drift-Schranke gegen knowledge_groups._rel ───────────────────────────
section("1. manifest_form == knowledge_groups._rel")
proben = [str(REAL_ROOT / "data/rag/a/b.md"), "/mnt/rag/share_1/x.pdf", "data/rag/c/d.pdf",
          "/mnt/rag/share_10/y.one", str(REAL_ROOT / "data/rag/Ordner mit Leerzeichen/ä.md")]
for p in proben:
    check(f"gleich fuer {p.replace(str(REAL_ROOT), '<root>')}",
          wg.manifest_form(p) == kg._rel(p), f"{wg.manifest_form(p)!r} != {kg._rel(p)!r}")

# ── Sandkasten ──────────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="wg_iso_"))
wg.ORDNER = TMP / "graph"
wg.PROJECT_ROOT = TMP / "proj"
wg._zuruecksetzen_fuer_test()
if not str(wg._o()).startswith(str(TMP)) or not str(wg.absolut("data/rag/x")).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)
P = wg.PROJECT_ROOT


def quell_dateien():
    d = wg._o() / "quellen"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def ent(name, typ="system"):
    return {"name": name, "typ": typ, "beschreibung": ""}


# ── 2. Eintritte, ausgefuehrt ───────────────────────────────────────────────
section("2. Kein Pfad ausserhalb von data/rag/ und /mnt/rag/")
VERBOTEN = [str(P / "data/erfahrung/x.md"), str(P / "data/knowledge/x.md"),
            str(P / "data/logs/a.log"), str(P / "data/rag2/x.md"),
            str(P / "data/rag/../logs/x.md"), "/etc/passwd", "mnt/ragx/y.pdf",
            "/mnt/rag", str(P / "data/rag"), "", "/mnt/rag2/share/x.pdf"]
ERLAUBT = [str(P / "data/rag/a/b.md"), "/mnt/rag/share_1/c.pdf", "data/rag/z/y.docx"]
# Positivkontrolle: die erlaubten MUESSEN durchgehen, sonst ist "nichts kam
# hinein" trivial wahr.
pos = [wg.quelle_schreiben(p, 1.0, [ent("Contoso")], []) for p in ERLAUBT]
check("Positivkontrolle: erlaubte Pfade werden gespeichert", all(pos) and len(quell_dateien()) == 3,
      f"{pos}, {len(quell_dateien())} Dateien")
# Abgebrochen wird nur, wenn GAR NICHTS durchgeht – dann kann die Messung
# nicht laufen. Fehlt nur einer, ist das ein Befund (FAIL oben), kein Abbruch
# (Register: ein Guard mit Exit 2 muss beide Ursachen trennen).
if not any(pos):
    print("ABBRUCH – Positivkontrolle gescheitert, die Folgepruefungen waeren trivial")
    sys.exit(2)
for f in quell_dateien():
    f.unlink()
wg._zuruecksetzen_fuer_test()

for p in VERBOTEN:
    check(f"quelle_schreiben weist ab: {p.replace(str(P), '<proj>') or '(leer)'}",
          wg.quelle_schreiben(p, 1.0, [ent("X")], []) is False)
    check(f"einreihen weist ab: {p.replace(str(P), '<proj>') or '(leer)'}",
          wg.einreihen(p, 1.0) is False)
check("nach allen Versuchen: keine Quelle abgelegt", quell_dateien() == [],
      str(quell_dateien()))
check("nach allen Versuchen: Warteschlange leer", wg.warteschlange_laenge() == 0)

# Umbenennen in einen verbotenen Ort ENTFERNT, statt zu verschieben
wg.quelle_schreiben(ERLAUBT[0], 1.0, [ent("A")], [])
wg.umbenennen(ERLAUBT[0], str(P / "data/erfahrung/b.md"))
check("Umbenennen nach data/erfahrung entfernt die Quelle", quell_dateien() == [],
      str([json.loads(f.read_text())["pfad"] for f in quell_dateien()]))
wg.quelle_schreiben(ERLAUBT[0], 1.0, [ent("A")], [])
wg.praefix_umbenennen(str(P / "data/rag/a"), str(P / "data/knowledge/a"))
check("Ordner nach data/knowledge umbenennen entfernt die Quellen", quell_dateien() == [])

# Von Hand gelegte Datei mit verbotenem Pfad wird nicht gelesen
(wg._o() / "quellen").mkdir(parents=True, exist_ok=True)
(wg._o() / "quellen" / "fremd.json").write_text(json.dumps(
    {"pfad": "data/erfahrung/x.md", "mtime": 1, "entitaeten": [ent("Geheim")], "relationen": []}))
wg._zuruecksetzen_fuer_test()
check("eine von Hand abgelegte Quelle mit verbotenem Pfad bleibt draussen",
      wg.quellen_alle() == [] and wg.kennzahlen()["entitaeten"] == 0,
      str([q["pfad"] for q in wg.quellen_alle()]))
(wg._o() / "quellen" / "fremd.json").unlink()
(wg._o() / "queue.json").write_text(json.dumps(
    {"eintraege": {"data/knowledge/x.md": {"mtime": 1}, "data/rag/a/ok.md": {"mtime": 1}}}))
wg._zuruecksetzen_fuer_test()
check("eine verbotene Zeile in queue.json wird beim Laden verworfen",
      [m for m, _ in wg.warteschlange()] == ["data/rag/a/ok.md"],
      str([m for m, _ in wg.warteschlange()]))
wg.warteschlange_leeren()

# ── 2b. Regel ueber den AST: jeder Eintritt prueft ──────────────────────────
section("2b. REGEL: jede oeffentliche Funktion mit Pfadparameter prueft")
PFAD_PARAM = {"pfad", "pfade", "alt", "neu", "prefix", "alt_prefix", "neu_prefix"}
PRUEFER = {"_erlaubt", "ist_graph_pfad"}
# Ausnahmen mit Grund – jede einzeln, keine Sammelfreigabe.
AUSNAHMEN = {"manifest_form": "reine Umrechnung, liest und schreibt nichts"}


def eintritte(quelltext: str) -> tuple[list[str], list[str]]:
    """(geprueft, ungeprueft) ueber einen Fixpunkt: geprueft ist, wer einen
    Pruefer ruft oder eine geprueft-Funktion."""
    baum = ast.parse(quelltext)
    fns = {f.name: f for f in baum.body if isinstance(f, ast.FunctionDef)}

    def gerufen(f):
        return {n.func.id for n in ast.walk(f)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    ok = set(PRUEFER)
    while True:
        neu = {n for n, f in fns.items() if n not in ok and gerufen(f) & ok}
        if not neu:
            break
        ok |= neu
    ziel = [n for n, f in fns.items() if not n.startswith("_") and n not in AUSNAHMEN
            and {a.arg for a in f.args.args} & PFAD_PARAM]
    return sorted(n for n in ziel if n in ok), sorted(n for n in ziel if n not in ok)


# Positivkontrolle der Regel: eine Funktion OHNE Pruefung muss auffallen.
_, schlecht = eintritte("def _erlaubt(m):\n    return True\n"
                        "def gut(pfad):\n    return _erlaubt(pfad)\n"
                        "def boese(pfad):\n    open(pfad, 'w')\n")
check("Positivkontrolle: die Regel erkennt eine ungepruefte Funktion", schlecht == ["boese"],
      str(schlecht))
gut, schlecht = eintritte((ROOT / "backend/wissensgraph.py").read_text(encoding="utf-8"))
print(f"    ({len(gut)} Eintritte gezaehlt: {', '.join(gut)})")
check("mindestens die bekannten Eintritte sind erfasst",
      {"quelle_schreiben", "einreihen", "umbenennen", "quellen_entfernen",
       "pflege_entfernt", "pflege_umbenannt"} <= set(gut), str(gut))
check("kein oeffentlicher Pfad-Eintritt ohne Pruefung", schlecht == [], str(schlecht))

# ── 3. Abgleich reiht nur Erlaubtes ein ─────────────────────────────────────


class FakeVS:
    def __init__(self, idx):
        self.idx = dict(idx)

    def get_indexed_files(self):
        return dict(self.idx)


class FakeK(types.ModuleType):
    def __init__(self, idx, folders):
        super().__init__("fake_knowledge")
        self.vs = FakeVS(idx)
        self.folders = list(folders)
        self._reindex_lock = threading.Lock()
        self._nutzbare_ordner = kn._nutzbare_ordner        # ECHT
        self._verwaiste_dateien = kn._verwaiste_dateien    # ECHT

    def _get_vector_store(self):
        return self.vs

    def _get_folders(self):
        return list(self.folders)


section("3. Abgleich reiht nur erlaubte Pfade ein")
for d in ("data/rag/a", "data/rag/b", "data/erfahrung", "data/knowledge"):
    (P / d).mkdir(parents=True, exist_ok=True)
fk = FakeK({str(P / "data/erfahrung/e.md"): 1.0, str(P / "data/knowledge/k.md"): 1.0,
            str(P / "data/rag/a/x.md"): 2.0, "/mnt/rag/share_1/y.pdf": 3.0},
           [P / "data/rag/a"])
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
eingereiht = sorted(m for m, _ in wg.warteschlange())
check("eingereiht sind genau die beiden erlaubten",
      eingereiht == ["data/rag/a/x.md", "mnt/rag/share_1/y.pdf"], str(eingereiht))
check("die beiden verbotenen sind als 'ausserhalb' gezaehlt", erg.get("ausserhalb") == 2, str(erg))
wg.warteschlange_leeren()

# ── 4. Bereinigen loescht nie aus Versehen ──────────────────────────────────
section("4. Bereinigen loescht nie aus Versehen")


def graph_mit(*pfade):
    for f in quell_dateien():
        f.unlink()
    wg._zuruecksetzen_fuer_test()
    for p in pfade:
        wg.quelle_schreiben(p, 1.0, [ent("E " + Path(p).name)], [])


def bestand():
    return sorted(wg.quellen_index())


A1, A2 = str(P / "data/rag/a/x.md"), str(P / "data/rag/a/y.md")
B1 = str(P / "data/rag/b/z.md")
(P / "data/rag/a/x.md").write_text("x")          # Ordner a ist NICHT leer

# Positivkontrolle: der Regelfall loescht wirklich – sonst waeren alle
# "loescht nicht"-Pruefungen darunter trivial wahr.
graph_mit(A1, A2, B1)
fk = FakeK({A1: 1.0, B1: 1.0}, [P / "data/rag/a", P / "data/rag/b"])
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
check("Positivkontrolle: eine von zwei Dateien fehlt im Index → genau sie geht",
      bestand() == ["data/rag/a/x.md", "data/rag/b/z.md"] and erg["bereinigt"] == 1,
      f"{bestand()} {erg}")
if erg.get("bereinigt") != 1:
    print("ABBRUCH – der Regelfall loescht nicht, die Schutzpruefungen waeren trivial")
    sys.exit(2)

graph_mit(A1, A2, B1)
fk = FakeK({A1: 1.0}, [])
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
check("leere Ordnerliste: nichts bereinigt", erg["bereinigt"] == 0 and len(bestand()) == 3, str(erg))
check("leere Ordnerliste: der Grund wird genannt", "keine Wissensordner" in erg["bereinigen"],
      erg["bereinigen"])

graph_mit(A1, A2, B1)
(P / "data/rag/b").mkdir(exist_ok=True)               # b ist LEER, Graph fuehrt b/z
fk = FakeK({A1: 1.0, A2: 1.0}, [P / "data/rag/a", P / "data/rag/b"])
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
check("abgehaengter (leerer) Ordner: seine Quelle bleibt", "data/rag/b/z.md" in bestand(),
      f"{bestand()} {erg}")

graph_mit(A1, A2, B1)
fk = FakeK({A1: 1.0}, [P / "data/rag/a", P / "data/rag/b"])
fk._reindex_lock.acquire()
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
fk._reindex_lock.release()
check("waehrend eines Neu-Indizierens: nichts bereinigt", len(bestand()) == 3,
      f"{bestand()} {erg}")

graph_mit(A1, A2, B1)
fk = FakeK({}, [P / "data/rag/a", P / "data/rag/b"])
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
check("leerer Index (abgebrochener Neuaufbau): nichts bereinigt", len(bestand()) == 3,
      f"{bestand()} {erg}")

for d in ("data/rag/share_1", "data/rag/share_10"):
    (P / d).mkdir(parents=True, exist_ok=True)
    (P / d / "da.md").write_text("x")
S1, S10 = str(P / "data/rag/share_1/da.md"), str(P / "data/rag/share_10/weg.md")
graph_mit(S1, S10)
fk = FakeK({S1: 1.0}, [P / "data/rag/share_1"])        # share_10 ist kein Ordner der Liste
wgx._wissen = lambda: fk
erg = wgx.abgleich(gruppen=[])
check("share_1 trifft share_10 nicht (Praefix mit Trenner)", "data/rag/share_10/weg.md" in bestand(),
      f"{bestand()} {erg}")

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
