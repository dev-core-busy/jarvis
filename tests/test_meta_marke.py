"""Meta-Bloecke zwischen zwei U+2063: nicht vorlesen, nicht als Download werten.

GEMELDET 2026-10-26 von einem Docker-Anwender, zwei Befunde:

1. Vorlesen: ein vorgeschalteter Proxy klammert Meta-Angaben (verbesserter
   Prompt, Eskalation, Quellenliste) in U+2063. Web und Android-App lasen sie
   vor ("[Prompt optimiert] ...").
2. Fehlalarm "Konnte nicht zum Download bereitgestellt werden": Dateinamen, die
   die Antwort als QUELLEN nennt, landeten als fehlende Downloads im roten
   Kasten. Zwei Wege dorthin – die Quellenliste im Meta-Block des Proxys und
   ein Name, den die Wissenssuche dieses Laufs geliefert hat.

Geprueft wird die WIRKUNG:
  A. ``ohne_meta`` – dieselben Faelle wie ``VorleseTextTest.kt`` (Android).
  B. ``/api/tts`` filtert, bevor der Text an die Sprachsynthese geht (AST).
  C. ``_deliver_docs`` wirklich ausgefuehrt (Harness aus test_doc_delivery):
     Positivkontrolle "eine nie erzeugte Datei wird gemeldet" VOR den
     Entwarnungen; Quellen aus Werkzeug-Ergebnis und Meta-Block warnen nicht;
     ein Name aus einem MODELL-Zwischentext warnt weiterhin; Seiten-Geschwister
     aus einem Werkzeug-Ergebnis werden weiterhin ausgeliefert.

    python3 tests/test_meta_marke.py
"""
import ast
import asyncio
import importlib.util
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


M = "⁣"

print("\n=== A. ohne_meta ===")
try:
    from backend.meta_marke import ohne_meta
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.meta_marke nicht ladbar: {e}")
    sys.exit(2)
check("ohne Marke unveraendert", ohne_meta("Hallo Welt") == "Hallo Welt")
r = ohne_meta(f"Antwort {M}[Prompt optimiert] xyz{M} Rest")
check("Block wird entfernt", r == "Antwort   Rest", repr(r))
r = ohne_meta(f"{M}x{M} A {M}y{M} B {M}z{M}")
check("mehrere Bloecke", r == "  A   B  ", repr(r))
r = ohne_meta(f"Antwort {M}Rest")
check("lose Marke entfernt nur sich selbst (Rest bleibt hoerbar)", r == "Antwort Rest", repr(r))
check("nur Meta ergibt leer", ohne_meta(f"{M}[Quellen] a.pdf{M}").strip() == "")
check("None/leer wirft nicht", ohne_meta("") == "" and ohne_meta(None) == "")

print("\n=== B. /api/tts filtert vor der Synthese ===")
main_src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(main_src)
fn = next((n for n in ast.walk(baum)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "tts_synthesize"), None)
check("tts_synthesize gefunden (Positivkontrolle)", fn is not None)
zuw = []
if fn is not None:
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "text" for t in n.targets):
            zuw.append(n)
check("genau EINE Zuweisung an `text`", len(zuw) == 1, str(len(zuw)))


def _ruft(knoten, name):
    return any(isinstance(c, ast.Call) and (
        (isinstance(c.func, ast.Name) and c.func.id == name)
        or (isinstance(c.func, ast.Attribute) and c.func.attr == name))
        for c in ast.walk(knoten))


check("... und sie laeuft durch ohne_meta()", bool(zuw) and _ruft(zuw[0], "ohne_meta"),
      ast.unparse(zuw[0]) if zuw else "")

print("\n=== C. _deliver_docs: Quellen sind keine fehlenden Downloads ===")
spec = importlib.util.spec_from_file_location("_dd", ROOT / "tests" / "test_doc_delivery.py")
dd = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(dd)
    EXT = dd.hole_liefer_ext()
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Harness aus test_doc_delivery nicht ladbar: {e}")
    sys.exit(2)

WARN = "Konnte nicht zum Download"

with tempfile.TemporaryDirectory() as tmp:
    tmpdir = Path(tmp)
    arbeit = tmpdir / "arbeit"
    arbeit.mkdir()
    deliver, _clean = dd.baue(tmpdir, dd.DokStub(), lauf=dd.LaufTmpStub(arbeit=arbeit))
    jetzt = time.time() - 5

    def lauf(schritte):
        """schritte: [(text, melden, aus_werkzeug)] im selben Lauf -> (gesendet, dauerhaft)."""
        s = dd.AgentStub(EXT)
        gesehen = set()
        for text, melden, aus_wz in schritte:
            asyncio.run(deliver(s, None, text, gesehen, "u", jetzt, melden, aus_werkzeug=aus_wz))
        return s.gesendet

    def warnt(gesendet, name):
        return any(WARN in m and name in m for m in gesendet)

    eindeutig = lambda stamm, ext="pdf": f"{stamm}_{uuid.uuid4().hex[:6]}.{ext}"  # noqa: E731

    # Messaufbau-Kontrolle ZUERST, und zwar ueber einen Weg, den keine der
    # Sabotagen unten beruehrt (Liefer-Marker, Zweig m): kommt dort keine
    # Warnung an, faengt der Harness die Meldungen nicht – Exit 2. Ob ein
    # BLOSSER Name gemeldet wird, ist dagegen eine Produkt-Eigenschaft und
    # gehoert als FAIL gezaehlt, nicht als "konnte nicht laufen" (Register:
    # ein Guard mit Exit 2 muss zwei Ursachen trennen).
    nm = f"/tmp/{eindeutig('gibtsnicht', 'pptx')}"
    g = lauf([(f"[[JARVIS_DELIVER:{nm}]]", True, False)])
    if not any(WARN in m for m in g):
        print(f"ABBRUCH: der Harness faengt keine Warnung – Messung blind: {g}")
        sys.exit(2)

    n0 = eindeutig("bericht", "xlsx")
    g = lauf([(f"Fertig: {n0}", True, False)])
    check("Positivkontrolle: ein nie erzeugter blosser Name wird gemeldet", warnt(g, n0), str(g))

    n1 = eindeutig("handbuch")
    g = lauf([(f"Treffer (Quelle: {n1}, Seite 3): ...", False, True),
              (f"Laut Handbuch gilt X. Quelle: {n1}", True, False)])
    check("Quelle aus der Wissenssuche dieses Laufs: KEINE Warnung", not warnt(g, n1), str(g))

    n2 = eindeutig("handbuch")
    g = lauf([(f"Ich lege {n2} an.", False, False),
              (f"Fertig: {n2}", True, False)])
    check("Name nur aus einem MODELL-Zwischentext: weiterhin gemeldet", warnt(g, n2), str(g))

    n3 = eindeutig("richtlinie")
    g = lauf([(f"Antwort ohne Datei.{M}Quellen: {n3}{M}", True, False)])
    check("Quelle im U+2063-Meta-Block: KEINE Warnung", not warnt(g, n3), str(g))
    g = lauf([(f"Antwort ohne Datei. Quellen: {n3}", True, False)])
    check("... derselbe Text OHNE Marken warnt (Gegenkontrolle)", warnt(g, n3), str(g))

    pfad = f"/tmp/{eindeutig('gibtsnicht', 'pptx')}"
    g = lauf([(f"Antwort.{M}Quelle: {pfad}{M}", True, False)])
    check("Pfad im Meta-Block: KEINE Warnung", not any(WARN in m for m in g), str(g))
    g = lauf([(f"Antwort. Quelle: {pfad}", True, False)])
    check("... derselbe Pfad OHNE Marken warnt (Gegenkontrolle)", any(WARN in m for m in g), str(g))

    stamm = f"seite_{uuid.uuid4().hex[:6]}"
    (arbeit / f"{stamm}-1.jpg").write_bytes(b"\xff\xd8\xffegal")
    g = lauf([(f"Erzeugt: {stamm}.jpg", False, True)])
    check("Seiten-Geschwister aus einem Werkzeug-Ergebnis: weiterhin ausgeliefert",
          any("/api/documents/" in m for m in g), str(g))

print("\n=== D. der echte Werkzeug-Aufruf gibt aus_werkzeug=True mit ===")
ag = ast.parse((ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))
rufe = [c for c in ast.walk(ag) if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute) and c.func.attr == "_deliver_docs"]
check("Aufrufe von _deliver_docs gefunden (Positivkontrolle)", len(rufe) >= 2, str(len(rufe)))


def _kw(c, name):
    return next((k.value for k in c.keywords if k.arg == name), None)


wz = [c for c in rufe if len(c.args) >= 2 and isinstance(c.args[1], ast.Name)
      and c.args[1].id in ("_sichtbar", "result_str")]
check("genau EIN Aufruf mit dem Werkzeug-Ergebnis", len(wz) == 1, str(len(wz)))
check("... mit aus_werkzeug=True", len(wz) == 1 and isinstance(_kw(wz[0], "aus_werkzeug"), ast.Constant)
      and _kw(wz[0], "aus_werkzeug").value is True)
andere = [c for c in rufe if c not in wz]
check("die Endantwort-Aufrufe setzen aus_werkzeug NICHT",
      andere and all(_kw(c, "aus_werkzeug") is None for c in andere),
      str([ast.unparse(c)[:80] for c in andere]))

ok = sum(res)
print(f"\nErgebnis: {ok}/{len(res)}")
sys.exit(0 if all(res) else 1)
