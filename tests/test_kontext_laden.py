#!/usr/bin/env python3
"""Waechter: ein Kontext kommt NUR GEHEILT von Platte in den Speicher.

DER VORFALL (ECHT, 2026-08-30): Auf „generiere ein kleines, fotorealistisches
Bild einer gruenen Kuh mit roten Hoernern" delegierte der Agent
`{"role": "image_builder", "task": "Erstelle ein 300x300 Pixel Comic-Bild einer
schnell rennenden Maus."}` – und lieferte eine Maus.

GEMESSEN in `data/chats/nexusandreas.bender/dbcbe98a0f9d/context.json`:

    [16] user   text  'generiere ein 300 auf 300 Pixel Comic Bild einer … Maus'
    [17] user   text  'generiere ein kleines, fotorealistisches Bild einer … Kuh'
    [18] model  CALL->delegate

Zwei Benutzerfragen hintereinander, ohne Antwort dazwischen. Die Maus-Frage
stand seit dem 26.08. unbeantwortet im Kontext; das Modell sah zwei offene
Fragen und arbeitete die AELTERE ab.

URSACHE – und das ist die eigentliche Lehre: `_verlauf_reparieren` existierte
seit dem Vortag und arbeitet KORREKT (Abschnitt 2 misst das nach). Sie hing nur
am Lade-Zweig in `run_task`. Die beiden Pfade in `main.py` – „Nachricht
loeschen" und „Nachricht editieren" – luden denselben Kontext UNGEHEILT in
dasselbe `_user_histories`. Danach findet der Agent den Verlauf im Speicher und
laedt ihn nie wieder: die Reparatur war fuer die restliche Prozesslebensdauer
tot. Der Benutzer hatte die Maus-Frage geloescht – genau ueber diesen Pfad.

**Eine Schutzmassnahme an EINEM von mehreren Zugaengen ist keine.**

Dieser Test fuehrt die ECHTEN Funktionen aus (per `ast` aus `backend/agent.py`
geschnitten – ein Import zoege `backend.config` und schriebe die
Live-settings.json zurueck) und prueft die REGEL statt einer Liste: jede Stelle,
die `load_context` liest oder `_user_histories` befuellt, muss ueber
`geheilter_sitzungskontext` gehen. Damit faellt auch eine KUENFTIGE vierte
Ladestelle auf.

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import ast
import sys
import textwrap
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
AGENT_PY = WURZEL / "backend" / "agent.py"
MAIN_PY = WURZEL / "backend" / "main.py"

_ok = 0
_fail = 0


def pruef(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {text}")


def abbruch(text):
    print(f"KONNTE NICHT LAUFEN: {text}")
    sys.exit(2)


for _p in (AGENT_PY, MAIN_PY):
    if not _p.exists():
        abbruch(f"{_p} fehlt")

A_QUELLE = AGENT_PY.read_text(encoding="utf-8")
M_QUELLE = MAIN_PY.read_text(encoding="utf-8")
A_ZEILEN = A_QUELLE.splitlines()
A_BAUM = ast.parse(A_QUELLE)
M_BAUM = ast.parse(M_QUELLE)


def _segment(node) -> str:
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return textwrap.dedent("\n".join(A_ZEILEN[start - 1:node.end_lineno]))


def _funktion(baum, name):
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _ohne_kommentare(text: str) -> str:
    """Kommentarzeilen entfernen – ein Waechter, der seine eigene Begruendung
    liest, prueft nichts (Register: neun belegte Faelle)."""
    return "\n".join(z for z in text.splitlines() if not z.strip().startswith("#"))


# ═══════════════════════════════════════════════════════════════════════════
print("1. Die EINE Ladefunktion existiert und heilt")

fn = _funktion(A_BAUM, "geheilter_sitzungskontext")
if fn is None:
    abbruch("geheilter_sitzungskontext fehlt in agent.py – Fix nicht vorhanden?")
_src = _ohne_kommentare(ast.get_source_segment(A_QUELLE, fn) or "")
pruef("_verlauf_reparieren" in _src, "die Ladefunktion ruft die Reparatur nicht auf")
pruef("load_context" in _src, "die Ladefunktion liest den Kontext gar nicht")
pruef("save_context" in _src,
      "die Heilung wird nicht zurueckgeschrieben – der beschaedigte Stand bleibt auf Platte")

# ═══════════════════════════════════════════════════════════════════════════
print("\n2. Die Reparatur selbst: der ECHTE Vorfall, echte Funktion")

KLS = next((n for n in ast.walk(A_BAUM)
            if isinstance(n, ast.ClassDef) and n.name == "JarvisAgent"), None)
if KLS is None:
    abbruch("Klasse JarvisAgent nicht gefunden")
rep = next((n for n in KLS.body
            if isinstance(n, ast.FunctionDef) and n.name == "_verlauf_reparieren"), None)
ibf = _funktion(A_BAUM, "ist_benutzerfrage")
if rep is None or ibf is None:
    abbruch("_verlauf_reparieren oder ist_benutzerfrage fehlt")

marken = None
for n in A_BAUM.body:
    if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "INTERNE_VERLAUFS_MARKEN" for t in n.targets):
        marken = _segment(n)
if marken is None:
    abbruch("INTERNE_VERLAUFS_MARKEN nicht gefunden")

_ns = {"print": lambda *a, **k: None}
exec(marken, _ns)
exec(_segment(ibf), _ns)
exec("class _A:\n" + textwrap.indent(_segment(rep), "    "), _ns)
_A = _ns["_A"]
_ist_frage = _ns["ist_benutzerfrage"]


class _P:
    def __init__(self, text=None, fc=None, fr=None):
        self.text = text
        self.function_call = fc
        self.function_response = fr


class _E:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


def _txt(rolle, t):
    return _E(rolle, [_P(text=t)])


def _call():
    return _E("model", [_P(fc=object())])


def _resp():
    return _E("user", [_P(fr=object())])


MAUS = "generiere ein 300 auf 300 Pixel Comic Bild einer schnell rennenden Maus"
KUH = "generiere ein kleines, fotorealistisches Bild einer gruenen Kuh mit roten Hoernern"


def _hat_maus(verlauf):
    return any(_ist_frage(e) and MAUS[:30] in (e.parts[0].text or "") for e in verlauf)


# (a) Zustand VOR dem Kuh-Lauf – die Maus-Frage ist der letzte Eintrag.
v = [_txt("user", "Drache"), _call(), _resp(), _txt("model", "Hier ist das Bild"),
     _txt("user", MAUS)]
weg = _A._verlauf_reparieren(v)
pruef(weg == 1, f"unbeantwortete Frage am Ende nicht entfernt (weg={weg})")
pruef(not _hat_maus(v), "die unbeantwortete Maus-Frage steht noch im Verlauf")

# (b) Der gemeldete Zustand: zwei Fragen hintereinander.
v = [_txt("user", "Drache"), _call(), _resp(), _txt("model", "Hier ist das Bild"),
     _txt("user", MAUS), _txt("user", KUH), _call(), _resp(), _txt("model", "fertig")]
_A._verlauf_reparieren(v)
pruef(not _hat_maus(v), "bei zwei Fragen hintereinander bleibt die aeltere stehen")
pruef(any(_ist_frage(e) and KUH[:30] in (e.parts[0].text or "") for e in v),
      "die AKTUELLE Frage wurde mitentfernt – das waere schlimmer als der Fehler")

# (c) Gegenrichtung: ein gesunder Verlauf darf NICHT angefasst werden.
v = [_txt("user", "Frage A"), _call(), _resp(), _txt("model", "Antwort A"),
     _txt("user", "Frage B"), _txt("model", "Antwort B")]
vorher = len(v)
weg = _A._verlauf_reparieren(v)
pruef(weg == 0 and len(v) == vorher,
      f"gesunder Verlauf wurde beschaedigt (weg={weg}, {vorher}->{len(v)})")

# (d) Offener Werkzeugaufruf ohne Ergebnis.
v = [_txt("user", "Frage"), _call()]
_A._verlauf_reparieren(v)
pruef(not any(getattr(p, "function_call", None) for e in v for p in e.parts),
      "function_call ohne function_response bleibt stehen")

# ═══════════════════════════════════════════════════════════════════════════
print("\n3. DIE REGEL: kein Aufrufer laedt an der Heilung vorbei")
# Geprueft wird die EIGENSCHAFT, nicht eine gepflegte Liste – eine kuenftige
# vierte Ladestelle faellt damit von selbst auf.

verstoesse = []
for datei, quelle in (("backend/agent.py", A_QUELLE), ("backend/main.py", M_QUELLE)):
    for nr, zeile in enumerate(quelle.splitlines(), 1):
        nackt = zeile.strip()
        if nackt.startswith("#") or "load_context" not in nackt:
            continue
        # Die Definition der Heilfunktion selbst und der Sitzungs-Speicher
        # duerfen load_context natuerlich benutzen.
        if "def " in nackt or "chat_sessions.py" in datei:
            continue
        verstoesse.append(f"{datei}:{nr}  {nackt[:88]}")

# In agent.py ist genau EIN Vorkommen erlaubt: das in geheilter_sitzungskontext.
erlaubt = _ohne_kommentare(ast.get_source_segment(A_QUELLE, fn) or "")
erlaubte_zeilen = {z.strip() for z in erlaubt.splitlines() if "load_context" in z}
offen = [v for v in verstoesse
         if not any(e and e in v for e in erlaubte_zeilen)]
pruef(not offen,
      "load_context wird an der Heilung vorbei aufgerufen:\n      "
      + "\n      ".join(offen))

# ═══════════════════════════════════════════════════════════════════════════
print("\n4. Beide main.py-Pfade nutzen die Heilfunktion")

pruef("geheilter_sitzungskontext" in M_QUELLE,
      "main.py importiert die Heilfunktion nirgends")
pruef(M_QUELLE.count("geheilter_sitzungskontext") >= 2,
      f"nur {M_QUELLE.count('geheilter_sitzungskontext')} Verwendung(en) in main.py – "
      f"es gibt ZWEI Pfade (loeschen und editieren)")

# Der Lade-Zweig in run_task darf den Dreizeiler nicht wieder selbst bauen.
rt = _funktion(A_BAUM, "run_task")
if rt is not None:
    rt_src = _ohne_kommentare(ast.get_source_segment(A_QUELLE, rt) or "")
    pruef("load_context" not in rt_src,
          "run_task laedt den Kontext wieder selbst statt ueber die Heilfunktion")

# ═══════════════════════════════════════════════════════════════════════════
print("\n5. Die Reparatur laeuft NICHT waehrend eines Laufs")
# Der Hauptagent ist geteilt; ein offener function_call ist dann der
# NORMALZUSTAND eines parallelen Laufs und wuerde weggeworfen.

for name in ("_execute_tool", "_run_headless"):
    f = _funktion(A_BAUM, name)
    if f is None:
        continue
    src = _ohne_kommentare(ast.get_source_segment(A_QUELLE, f) or "")
    pruef("_verlauf_reparieren" not in src,
          f"{name} ruft die Reparatur – die darf nur BEIM LADEN laufen")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
