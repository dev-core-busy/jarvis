#!/usr/bin/env python3
"""Waechter: die Zielordner-Auswahl unter /wissen bildet den EXAKTEN Baum ab.

Gemeldet 2026-09-24: "der Verzeichnisbaum unter /wissen -> Informationsextraktor
-> Zielordner wird nicht hierarchisch sortiert".

Gemessen wird die EIGENSCHAFT, nicht eine abgetippte Liste:
  * jeder Ordner steht VOR seinen Kindern,
  * ein Ordner und sein Teilbaum sind ein ZUSAMMENHAENGENDER Block
    (kein fremder Ordner dazwischen),
  * Geschwister alphabetisch ohne Ruecksicht auf Gross-/Kleinschreibung.
Damit faellt auch eine kuenftige Umstellung des Durchlaufs auf, ohne dass
jemand eine Erwartungsliste pflegt.

Dazu eine DRIFT-SCHRANKE: ``_kb_list_subfolders`` (Pulldown im
Informationsextraktor + Verschieben-Modal) und ``knowledge_folder_tree``
(Zielordner beim Verschieben einer Datei in den Einstellungen) muessen fuer
denselben Baum DIESELBE Reihenfolge liefern. Laufen sie auseinander, zeigt
dieselbe Ordnerstruktur je nach Bildschirm etwas anderes.

Die echten Funktionen werden per ``ast`` geschnitten und WIRKLICH AUSGEFUEHRT
– ob ein Kind unter seinem Elternordner landet, kann eine Quelltext-Pruefung
nicht beantworten. Sandkasten mit Exit 2: ein Lauf gegen die echten
Wissensordner wuerde ueber Netzfreigaben laufen und nichts belegen.
"""
import ast
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
WISSEN_JS = (WURZEL / "frontend" / "js" / "wissen.js").read_text(encoding="utf-8")

_ok = _fail = 0


def check(text, bedingung):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}")


def sicher(fn, info=""):
    """Eine Pruefung darf NICHT werfen – sonst endet der Lauf ohne Bilanzzeile
    und ist von 'nicht gelaufen' nicht zu unterscheiden."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        global _fail
        _fail += 1
        print(f"  FAIL {info or 'Aufruf'} wirft: {type(e).__name__}: {e}")
        return None


def schneide(name):
    baum = ast.parse(MAIN)
    for k in baum.body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return ast.get_source_segment(MAIN, k)
    print(f"FUNKTION {name} NICHT GEFUNDEN – Waechter kann nichts messen")
    sys.exit(2)


# ── Namens-Guard GANZ OBEN: gegen einen aelteren Stand bricht der Lauf sonst
#    mit nacktem SystemExit ab, bevor eine Bilanz entsteht.
for _n in ("_kb_baum_key", "_kb_list_subfolders", "knowledge_folder_tree"):
    schneide(_n)


# ── Sandkasten ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="ordnerbaum-test-"))
if not str(SAND).startswith(tempfile.gettempdir()):
    print("SANDKASTEN GREIFT NICHT – Abbruch statt Schreiben in den echten Bestand")
    sys.exit(2)

WURZEL_REL = "data/rag/handbuch"

# ⚠ DER BAUM BRAUCHT EINEN FRUEH EINSORTIERTEN ORDNER MIT KINDERN.
#   Mit nur einem Zweig ganz am Ende (wie "Vertraege" im gemeldeten Screenshot)
#   sieht selbst eine falsche Reihenfolge zufaellig richtig aus, und jede
#   Pruefung darunter waere trivial wahr.
BAUM = [
    "01 Systembasis",
    "02 Stat. Patientenverwaltung",
    "04 Station",
    "04 Station/A Visite",
    "04 Station/A Visite/tief",
    "04 Station/B Kurve",
    # ⚠ DIESER ORDNER MACHT DIE TUPEL-REGEL ERST MESSBAR. Sein Name beginnt mit
    #   dem eines anderen Ordners plus Leerzeichen (0x20 < 0x2F = '/'). Wer den
    #   ganzen Pfad als ZEICHENKETTE sortiert, schiebt ihn zwischen "04 Station"
    #   und dessen Kinder und zerreisst damit den Teilbaum. Ohne diesen Fall
    #   waere `tuple(...)` eine Zeile, deren Entfernen nichts aendert.
    "04 Station Neu",
    "05 Arzt",
    "13 Telematikinfrastruktur",
    "Alpha",
    "Vertraege",
    "Vertraege/01 Patientenfuehrung",
    "Vertraege/02 Administration",
    # ⚠ Gross/Klein MUSS unterscheidbar sein: "Alpha, beta, gamma" ergibt
    #   case-sensitiv DIESELBE Reihenfolge – damit waere die Pruefung zahnlos.
    #   Mit "Gamma" trennen sich die Faelle: case-sensitiv Alpha, Gamma, beta;
    #   richtig (insensitiv) Alpha, beta, Gamma.
    "beta",
    "Gamma",
]
for p in BAUM:
    (SAND / WURZEL_REL / p).mkdir(parents=True, exist_ok=True)
# Versteckter Ordner und pending-Speicher duerfen NICHT auftauchen
(SAND / WURZEL_REL / ".versteckt").mkdir(exist_ok=True)
(SAND / WURZEL_REL / "pending").mkdir(exist_ok=True)


def _ist_pending(p):
    return "/pending" in str(p).replace("\\", "/")


knowledge = types.ModuleType("backend.tools.knowledge")
knowledge.PROJECT_ROOT = SAND
knowledge._is_pending_path = _ist_pending
knowledge._safe_exists = lambda p: Path(p).exists()
sys.modules.setdefault("backend", types.ModuleType("backend"))
sys.modules["backend.tools"] = types.ModuleType("backend.tools")
sys.modules["backend.tools.knowledge"] = knowledge


class _Rag:
    @staticmethod
    def anzeige(p):
        return str(p).split("/")[-1]


NS = {
    "os": os, "Path": Path, "sys": sys,
    "_kb_norm_rel": lambda p: str(p).strip("/"),
    "_rag": _Rag,
    "_kb_current_folder_list": lambda: [WURZEL_REL],
    "JSONResponse": lambda d: d,
    "app": types.SimpleNamespace(get=lambda *a, **k: (lambda f: f)),
    "Depends": lambda f: None,
    "require_knowledge_editor": None,
}
exec(schneide("_kb_baum_key"), NS)
exec(schneide("_kb_list_subfolders"), NS)

# knowledge_folder_tree traegt einen Dekorator -> den Rumpf ohne ihn ausfuehren
_ft_quelle = schneide("knowledge_folder_tree")
_ft_quelle = "\n".join(z for z in _ft_quelle.splitlines() if not z.startswith("@"))
exec(_ft_quelle, NS)


def liste():
    return NS["_kb_list_subfolders"](WURZEL_REL)


def rel_namen(eintraege):
    n = len(WURZEL_REL) + 1
    return [e["path"][n:] for e in eintraege]


print("=" * 72)
print("1. POSITIVKONTROLLE – der Messaufbau stellt den Regelfall her")
print("=" * 72)

eintraege = sicher(liste, "_kb_list_subfolders") or []
pfade = rel_namen(eintraege)
check(f"Unterordner gefunden ({len(pfade)})", len(pfade) == len(BAUM))
check("versteckte Ordner sind draussen", not any(p.startswith(".") for p in pfade))
check("pending-Speicher ist draussen", "pending" not in pfade)
# ⚠ Ohne diesen Fall ist jede Reihenfolge-Pruefung trivial wahr.
check("der Baum hat einen FRUEH einsortierten Ordner mit Kindern",
      "04 Station/A Visite" in pfade
      and pfade.index("04 Station") < pfade.index("13 Telematikinfrastruktur"))
check("der Baum ist mehr als zwei Ebenen tief", "04 Station/A Visite/tief" in pfade)

print()
print("=" * 72)
print("2. DER EXAKTE BAUM – Eigenschaft, nicht abgetippte Liste")
print("=" * 72)


def eltern(p):
    return p.rsplit("/", 1)[0] if "/" in p else None


# (a) Jeder Ordner steht VOR seinen Kindern.
fehler = [p for p in pfade
          if eltern(p) is not None and pfade.index(eltern(p)) > pfade.index(p)]
check(f"jeder Ordner steht vor seinen Kindern{'' if not fehler else ' – ' + str(fehler)}",
      not fehler)

# (b) Ein Ordner und sein Teilbaum sind ein ZUSAMMENHAENGENDER Block. Genau das
#     war der gemeldete Fehler: die Kinder von "04 Station" standen am Ende der
#     Liste, eingerueckt unter einem fremden Elternordner.
loecher = []
for i, p in enumerate(pfade):
    kinder = [j for j, q in enumerate(pfade) if q.startswith(p + "/")]
    if not kinder:
        continue
    if sorted(kinder) != list(range(i + 1, i + 1 + len(kinder))):
        loecher.append(p)
check(f"Teilbaeume sind zusammenhaengend{'' if not loecher else ' – ' + str(loecher)}",
      not loecher)

# (c) Geschwister alphabetisch, Gross/Klein egal.
unsortiert = []
for i in range(1, len(pfade)):
    a, b = pfade[i - 1], pfade[i]
    if eltern(a) == eltern(b) and a.lower() > b.lower():
        unsortiert.append((a, b))
check(f"Geschwister alphabetisch (Gross/Klein egal){'' if not unsortiert else ' – ' + str(unsortiert)}",
      not unsortiert)
check("Gross/Klein wirklich gemischt geprueft (Alpha < beta < Gamma)",
      sicher(lambda: pfade.index("Alpha") < pfade.index("beta") < pfade.index("Gamma"),
             "Gross/Klein-Reihenfolge"))

# (d) ``depth`` passt zum Pfad – der Client rueckt allein danach ein.
falsch = [e for e in eintraege
          if e["depth"] != e["path"][len(WURZEL_REL) + 1:].count("/") + 1]
check(f"depth passt zur Pfadtiefe{'' if not falsch else ' – ' + str(falsch)}", not falsch)

# (e) Unabhaengige Referenz: derselbe Baum, im Test selbst rekursiv gebildet.
def referenz(basis, praefix=""):
    out = []
    try:
        eintr = sorted(basis.iterdir(), key=lambda e: e.name.lower())
    except OSError:
        return out
    for e in eintr:
        if not e.is_dir() or e.name.startswith(".") or e.name == "pending":
            continue
        rel = f"{praefix}{e.name}"
        out.append(rel)
        out.extend(referenz(e, rel + "/"))
    return out


soll = referenz(SAND / WURZEL_REL)
check("deckungsgleich mit der unabhaengig gebildeten Tiefensuche", pfade == soll)

print()
print("=" * 72)
print("3. DRIFT-SCHRANKE – beide Zielordner-Auswahlen sortieren gleich")
print("=" * 72)

antwort = sicher(lambda: NS["knowledge_folder_tree"].__wrapped__
                 if hasattr(NS["knowledge_folder_tree"], "__wrapped__")
                 else NS["knowledge_folder_tree"], "folder_tree holen")
import asyncio
ft = sicher(lambda: asyncio.run(NS["knowledge_folder_tree"](user="test")), "folder_tree Lauf")
if ft is None:
    check("knowledge_folder_tree laeuft", False)
else:
    ft_pfade = [f["path"][len(WURZEL_REL) + 1:] for f in ft["folders"] if not f["is_root"]]
    check(f"gleiche Reihenfolge wie _kb_list_subfolders"
          f"{'' if ft_pfade == pfade else f' – folder_tree={ft_pfade[:6]} vs {pfade[:6]}'}",
          ft_pfade == pfade)
    check("folder_tree liefert den Wurzelordner als is_root",
          any(f["is_root"] for f in ft["folders"]))

print()
print("=" * 72)
print("4. REGELN – die Reihenfolge entsteht am SERVER, nicht im Client")
print("=" * 72)


def ohne_worte(py):
    """Kommentare UND Docstrings entfernen.

    ⚠ ``tokenize`` kennt nur ``#``-Kommentare – die Begruendungen dieses
    Projekts stehen ueberwiegend in DOCSTRINGS. Ein Filter, der die stehen
    laesst, laesst den Waechter seine eigene Erklaerung lesen."""
    baum = ast.parse(py)
    for k in ast.walk(baum):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (k.body and isinstance(k.body[0], ast.Expr)
                    and isinstance(k.body[0].value, ast.Constant)
                    and isinstance(k.body[0].value.value, str)):
                # Rumpf nie leeren -> sonst IndentationError
                k.body[0].value.value = ""
    return ast.unparse(baum)


roh_liste = schneide("_kb_list_subfolders")
code_liste = ohne_worte(roh_liste)
# Positivkontrolle des Filters: das Wort steht NUR im Docstring, der Code
# enthaelt es nicht. Ohne diese Zeile waere nicht zu sehen, ob der Filter greift.
check("Docstring-Filter greift (Begruendung entfernt)",
      "Schoenheitsschritt" in roh_liste and "Schoenheitsschritt" not in code_liste
      and "os.walk(" in code_liste)
check("_kb_list_subfolders sortiert ueber _kb_baum_key",
      "_kb_baum_key" in code_liste and ".sort(" in code_liste)

# Der Client darf NICHT nachsortieren: zwei Fassungen derselben Regel liefen
# beim naechsten Feinschliff auseinander.
def js_funktion(name):
    i = WISSEN_JS.find(f"function {name}(")
    if i < 0:
        return ""
    tiefe, j, start = 0, WISSEN_JS.find("{", i), None
    for k in range(j, len(WISSEN_JS)):
        if WISSEN_JS[k] == "{":
            tiefe += 1
            if start is None:
                start = k
        elif WISSEN_JS[k] == "}":
            tiefe -= 1
            if tiefe == 0:
                return WISSEN_JS[i:k + 1]
    return ""


uf = js_funktion("updateFolderOptions")
check("updateFolderOptions gefunden (Schnitt traegt)", "offer.map(" in uf)
check("updateFolderOptions sortiert NICHT selbst", ".sort(" not in uf)
check("updateFolderOptions rueckt allein nach depth ein", "f.depth" in uf)

print()
print("=" * 72)
shutil.rmtree(SAND, ignore_errors=True)
print(f"ERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
