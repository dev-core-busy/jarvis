#!/usr/bin/env python3
"""Waechter: ein aufgegebener Schema-Graph-Nachlauf bleibt nicht liegen.

Review 2026-11-10: ``_lauf_mit_nachlauf`` gab bei einer fremden Sperre nach
120 Versuchen (oder bei Abbruch) auf, das ``finally`` setzte nur
``_auto_aktiv`` zurueck – der vorgemerkte Auftrag blieb in ``_nachlauf``
stehen. Der naechste, fremde Lauf (``anstossen``) haette ihn mit den damaligen
Einstellungen ein zweites Mal ausgefuehrt, und der Upload selbst war still
verloren. Jetzt: beim Ende des Threads wird ein vorgemerkter Auftrag LAUT
verworfen, der aufgegebene Lauf meldet sich im Journal.

Gemessen am ECHTEN ``_lauf_mit_nachlauf`` (nur ``lauf`` ist eine Attrappe, mit
der echten Signatur ``lauf(ordner, abbruch=..., **kw)``), mit Positivkontrolle:
im Normalfall wird der Nachlauf abgeholt (zwei Laeufe, nichts verworfen).

    python3 tests/test_schema_graph_nachlauf.py     (Exit 0/1/2)
"""
import contextlib
import io
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail)[:300] if detail else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


# backend.config-Attrappe VOR jedem Import (der echte schreibt settings.json).
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(
    get_skill_states=lambda: {"schema_graph": {"enabled": True, "config": {}}})
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import schema_graph_index as I
except Exception as e:  # noqa: BLE001
    abbruch("schema_graph_index nicht importierbar: %r" % e)
if getattr(sys.modules.get("backend.config"), "__file__", None):
    abbruch("das ECHTE backend.config wurde geladen")
for name in ("_lauf_mit_nachlauf", "_nachlauf_sperre", "_abbruch", "LaeuftSchon", "lauf"):
    if not hasattr(I, name):
        abbruch("schema_graph_index.%s fehlt" % name)

LAEUFE = []


def lauf_attrappe(ordner, abbruch=None, **kw):
    """Echte Signatur von ``lauf``; merkt sich die Aufrufe."""
    LAEUFE.append((list(ordner), dict(kw)))


def lauf_gesperrt(ordner, abbruch=None, **kw):
    LAEUFE.append((list(ordner), dict(kw)))
    raise I.LaeuftSchon("Sperre eines anderen Prozesses")


def zustand(nachlauf, aktiv=True):
    with I._nachlauf_sperre:
        I._nachlauf = nachlauf
        I._auto_aktiv = aktiv
    LAEUFE.clear()


_orig_lauf = I.lauf
try:
    print("1. Positivkontrolle: im Normalfall wird der Nachlauf abgeholt")
    I.lauf = lauf_attrappe
    I._abbruch.clear()
    zustand({"ordner": ["b"], "muster": "*.sql"})
    puffer = io.StringIO()
    with contextlib.redirect_stdout(puffer):
        I._lauf_mit_nachlauf(["a"], muster="*.ddl")
    if len(LAEUFE) != 2:
        abbruch("Messaufbau: erwartet zwei Laeufe (Auftrag + Nachlauf), gemessen %d" % len(LAEUFE))
    check("(Positivkontrolle) Auftrag UND vorgemerkter Nachlauf laufen, je mit eigenen Einstellungen",
          LAEUFE[0] == (["a"], {"muster": "*.ddl"}) and LAEUFE[1] == (["b"], {"muster": "*.sql"}), LAEUFE)
    check("(Positivkontrolle) danach ist nichts vorgemerkt und nichts verworfen",
          I._nachlauf is None and I._auto_aktiv is False and "verworfen" not in puffer.getvalue(),
          puffer.getvalue()[-200:])

    print("2. Fremde Sperre, Abbruch: der vorgemerkte Auftrag bleibt NICHT liegen")
    I.lauf = lauf_gesperrt
    I._abbruch.set()
    zustand({"ordner": ["b"], "muster": "*.sql"})
    puffer = io.StringIO()
    with contextlib.redirect_stdout(puffer):
        I._lauf_mit_nachlauf(["a"], muster="*.ddl")
    aus = puffer.getvalue()
    check("der Thread gibt auf (ein Versuch, kein Lauf des Nachlaufs)", len(LAEUFE) == 1, LAEUFE)
    check("⚠ _nachlauf ist danach LEER – kein fremder Lauf fuehrt ihn spaeter aus",
          I._nachlauf is None, I._nachlauf)
    check("_auto_aktiv ist zurueckgesetzt", I._auto_aktiv is False)
    check("der aufgegebene Lauf meldet sich im Journal (Ordner und 'von Hand')",
          "aufgegeben" in aus and "'['a']'" in aus and "von Hand" in aus, aus[-300:])
    check("der verworfene Nachlauf meldet sich im Journal (Ordner und 'verworfen')",
          "verworfen" in aus and "'['b']'" in aus, aus[-300:])

    print("3. Abbruch ohne vorgemerkten Nachlauf: keine Falschmeldung")
    zustand(None)
    puffer = io.StringIO()
    with contextlib.redirect_stdout(puffer):
        I._lauf_mit_nachlauf(["a"])
    check("ohne Nachlauf steht kein 'verworfen' im Journal", "verworfen" not in puffer.getvalue(),
          puffer.getvalue()[-200:])
finally:
    I.lauf = _orig_lauf
    I._abbruch.clear()
    zustand(None, aktiv=False)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
