#!/usr/bin/env python3
"""Waechter: Wissensgruppen aus einem Request-Rumpf werden UEBERALL gleich normiert.

Anlass (2026-09-22): bei der Confluence-Einbindung fiel live auf, dass
``["", "  "]`` ein blosses ``if g`` ueberlebt – abgewiesen wurde richtig, der
Grund lautete aber "Keine Berechtigung fuer Gruppe(n):   " und schickte an die
falsche Stelle. Beim Nachmessen waren es nicht eine, sondern SECHS eigene
Fassungen derselben Normierung in ``backend/main.py``, und zwei davon warfen
bei einem Nicht-String (``{"groups": [1]}`` -> HTTP 500).

ZWEI TEILE, und die Aufteilung ist Absicht:
  1. Der Helfer wird GESCHNITTEN UND AUSGEFUEHRT – ob Leerraum wirklich
     verschwindet, kann eine Quelltext-Pruefung nicht beantworten.
  2. Die VERDRAHTUNG als REGEL ueber den Syntaxbaum: wer ``groups`` aus einem
     Request-Rumpf liest, muss durch den Helfer. Damit faellt auch eine
     KUENFTIGE Stelle auf, ohne dass jemand eine Liste pflegt.
"""
import ast
import pathlib
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
MAIN = WURZEL / "backend" / "main.py"

_ok = 0
_fail = 0


def check(text, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  \033[32m✓\033[0m {text}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {text}" + (f"  [{detail}]" if detail else ""))


def section(t):
    print(f"\n\033[1m{t}\033[0m")


def sicher(fn, *a):
    """Ein Wurf ist ein FEHLSCHLAG, kein Abbruch – sonst endet der Lauf ohne
    Bilanzzeile und ist von "nicht gelaufen" nicht zu unterscheiden."""
    try:
        return fn(*a), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"



def _ohne_worte(quelle: str) -> str:
    """Kommentare UND Docstrings durch Leerzeichen ersetzen.

    ⚠ ``tokenize`` KENNT NUR ``#``-KOMMENTARE – die Begruendungen dieses
    Projekts stehen ueberwiegend in DOCSTRINGS. Der von ``_gruppen_normieren``
    zitiert die beiden alten Fassungen woertlich, um zu erklaeren, warum es sie
    nicht mehr gibt: ohne diesen Filter liest der Waechter seine eigene
    Begruendung und meldet einen Fehler, den es nicht gibt (beim ersten Lauf
    genau so passiert).

    Ersetzt wird ZEICHENWEISE, nicht durch Neu-Zusammensetzen der Tokens – wer
    den Quelltext umbaut, prueft nicht mehr den Quelltext (Register).
    """
    import io
    import tokenize
    off, p = [], 0
    for z in quelle.splitlines(keepends=True):
        off.append(p)
        p += len(z)
    weg = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type == tokenize.COMMENT:
                weg.append((off[tok.start[0] - 1] + tok.start[1],
                            off[tok.end[0] - 1] + tok.end[1]))
    except Exception:
        pass
    try:
        for k in ast.walk(ast.parse(quelle)):
            if not isinstance(k, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if (k.body and isinstance(k.body[0], ast.Expr)
                    and isinstance(k.body[0].value, ast.Constant)
                    and isinstance(k.body[0].value.value, str)):
                n = k.body[0].value
                weg.append((off[n.lineno - 1] + n.col_offset,
                            off[n.end_lineno - 1] + n.end_col_offset))
    except Exception:
        pass
    aus = list(quelle)
    for a, e in weg:
        for i in range(a, min(e, len(aus))):
            if aus[i] != "\n":
                aus[i] = " "
    return "".join(aus)


QUELLE = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
NACKT = _ohne_worte(QUELLE)

# ── 1. Der Helfer, WIRKLICH ausgefuehrt ────────────────────────────────────
section("1. _gruppen_normieren – geschnitten und ausgefuehrt")

_def = [k for k in ast.walk(BAUM)
        if isinstance(k, ast.FunctionDef) and k.name == "_gruppen_normieren"]
check("der Helfer existiert genau einmal", len(_def) == 1, f"{len(_def)}x")
if len(_def) != 1:
    print("\n\033[1mErgebnis: ABBRUCH – ohne Helfer ist nichts messbar\033[0m")
    sys.exit(2)

ns = {}
exec(compile(ast.Module(body=[_def[0]], type_ignores=[]), "<schnitt>", "exec"), ns)
norm = ns["_gruppen_normieren"]

# Positivkontrolle ZUERST: eine Funktion, die alles verwirft, waere "sicher"
# und voellig wertlos – ohne diese Zeile ist jede Pruefung darunter trivial.
r, err = sicher(norm, ["a", "b"])
check("PK: gueltige Kennungen kommen durch", r == ["a", "b"], err or str(r))

for eingabe, erwartet, text in [
    (["  "],            [],            "⚠ ein String aus Leerzeichen wird verworfen (der gemeldete Fall)"),
    ([""],              [],            "ein leerer String wird verworfen"),
    (["", "  ", "a"],   ["a"],         "Leerraum neben einer echten Kennung"),
    ([" a "],           ["a"],         "Leerraum wird abgeschnitten, nicht der Wert"),
    (["b", "a"],        ["b", "a"],    "die Reihenfolge bleibt"),
    (["a", "a"],        ["a", "a"],    "bewusst NICHT dedupliziert (set_assignment tut es)"),
    ([1],               [],            "⚠ ein Nicht-String wird VERWORFEN, nicht zu '1' geraten"),
    ([None],            [],            "None wird verworfen"),
    ([{"id": "a"}],     [],            "ein dict wird verworfen"),
    ([],                [],            "die leere Liste bleibt leer"),
    (None,              [],            "None statt Liste ergibt []"),
    ("abc",             [],            "eine Zeichenkette ist keine Liste"),
    ({"a": 1},          [],            "ein dict ist keine Liste"),
]:
    r, err = sicher(norm, eingabe)
    check(text, r == erwartet, err or f"{eingabe!r} -> {r!r}, erwartet {erwartet!r}")

# Der Fall, der heute einen 500er erzeugte – gemessen, nicht behauptet.
_alt = lambda d: [g.strip() for g in (d.get("groups") or []) if str(g).strip()]
_r, _e = sicher(_alt, {"groups": [1]})
check("⚠ Gegenkontrolle: die ALTE Fassung wirft bei {'groups': [1]}",
      _e is not None and "AttributeError" in _e, _e or f"-> {_r!r}")

# ── 2. Verdrahtung als REGEL ───────────────────────────────────────────────
section("2. Regel – wer groups aus einem Rumpf liest, normiert")

# Ein Request-Rumpf ist ein schlichter NAME (`body`, `data`, …). Die Antwort
# der Gruppenverwaltung erkennt man daran, dass ihr Empfaenger ein AUFRUF ist
# (`kg.list_groups().get("groups", [])`) – die faellt damit von selbst heraus,
# ohne dass hier Namen gepflegt werden muessen.
AUSNAHMEN = {
    # Arbeitet auf den AUSGEHENDEN Gruppenobjekten der Gruppenverwaltung
    # (Liste von dicts), nicht auf einer Benutzereingabe.
    "_kb_strip_editor_fields",
}


def liest_rumpf_groups(knoten) -> bool:
    for n in ast.walk(knoten):
        # x["groups"]
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name):
            if isinstance(n.slice, ast.Constant) and n.slice.value == "groups":
                return True
        # x.get("groups")
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
                and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == "groups"):
            return True
    return False


def ruft_normierung(knoten) -> bool:
    for n in ast.walk(knoten):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "_gruppen_normieren":
            return True
    return False


kandidaten, verstoesse = [], []
for k in ast.walk(BAUM):
    if not isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    if k.name in AUSNAHMEN or k.name == "_gruppen_normieren":
        continue
    if not liest_rumpf_groups(k):
        continue
    kandidaten.append(k.name)
    if not ruft_normierung(k):
        verstoesse.append(f"{k.name}() Z{k.lineno}")

# Ohne Fundmenge waere die Regel ueber einer leeren Menge trivial wahr.
check("PK: die Regel findet ueberhaupt Stellen", len(kandidaten) >= 4,
      f"{len(kandidaten)}: {', '.join(kandidaten)}")
check("⚠ JEDE Stelle, die groups aus einem Rumpf liest, normiert",
      not verstoesse, "; ".join(verstoesse))

# Die beiden Fassungen, die es vorher gab, duerfen nicht zurueckkommen.
# Positivkontrolle des Filters: ohne sie waere jede Suche auf NACKT trivial
# wahr, sobald der Filter zu viel wegnimmt.
check("PK: der Filter entfernt den Docstring …",
      "EINE REGEL FUER ALLE ENDPUNKTE" in QUELLE
      and "EINE REGEL FUER ALLE ENDPUNKTE" not in NACKT, "Filter greift nicht")
check("PK: … und laesst den Code stehen",
      "def _gruppen_normieren" in NACKT, "Filter nimmt zu viel")
check("keine eigene Fassung mehr: 'if str(g).strip()'",
      "if str(g).strip()" not in NACKT, "alte Fassung zurueck")
check("keine eigene Fassung mehr: 'or []) if g]'",
      "or []) if g]" not in NACKT, "alte Fassung zurueck")

# ── 3. Die Typpruefung, die NICHT verschwinden darf ────────────────────────
section("3. /api/knowledge/assignments – leere Liste LOESCHT die Zuordnung")

_fn = [k for k in ast.walk(BAUM)
       if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
       and k.name == "knowledge_assignments_set"]
check("der Endpunkt existiert", len(_fn) == 1, f"{len(_fn)}x")
if _fn:
    src = ast.unparse(_fn[0])
    check("⚠ die Typpruefung steht weiterhin da (sonst loescht ein Tippfehler Zuordnungen)",
          "groups muss eine Liste sein" in src, "Typpruefung fehlt")
    # REIHENFOLGE: erst abweisen, dann normieren – andersherum waere aus
    # {"groups": "abc"} ein stilles [] und damit Datenverlust.
    i_typ = src.find("groups muss eine Liste sein")
    i_norm = src.find("_gruppen_normieren")
    check("⚠ und sie steht VOR der Normierung", 0 <= i_typ < i_norm,
          f"typ={i_typ}, norm={i_norm}")

print(f"\n\033[1mErgebnis: {_ok}/{_ok + _fail}\033[0m")
sys.exit(0 if _fail == 0 else 1)
