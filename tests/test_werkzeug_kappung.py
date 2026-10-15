#!/usr/bin/env python3
"""Waechter BSI H8-Nebenbefund: Prompt-Werkzeugmodus kappt NICHT mehr still.

Befund 2026-10-04 (H8): im Prompt-Werkzeugmodus ging jedes Werkzeugergebnis als
`result[:3000]` ans Modell – ohne Hinweis. Das Modell hielt den Ausschnitt fuer
vollstaendig, und die Endzeile des H8-Rahmens fehlte (der Rahmen ist die
Abgrenzung von Fremdtext; ohne Endzeile ist er offen).

Gemessen wird die WIRKUNG der echten Funktion (per AST aus backend/llm.py
geschnitten, ohne den Rest des Moduls zu importieren) mit einem echten
H8-Rahmen aus backend/werkzeug_rahmen.py, und als REGEL ueber den AST: die
Klartext-Nachricht fuer ein Werkzeugergebnis geht durch die Kappung, und kein
Werkzeugergebnis wird mehr per Slice gekuerzt.

Lauf:  python3 tests/test_werkzeug_kappung.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLM = ROOT / "backend" / "llm.py"
RAHMEN = ROOT / "backend" / "werkzeug_rahmen.py"
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name}" + (f" – {detail}" if detail else ""))


src = LLM.read_text(encoding="utf-8")
baum = ast.parse(src)
NAMEN = {"PROMPT_WERKZEUG_MAX", "_PROMPT_WERKZEUG_ENDE", "werkzeug_ergebnis_kappen"}
teile = []
for k in baum.body:
    if isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id in NAMEN
                                         for t in k.targets):
        teile.append(ast.get_source_segment(src, k))
    elif isinstance(k, ast.FunctionDef) and k.name in NAMEN:
        teile.append(ast.get_source_segment(src, k))
if len(teile) != 3:
    print(f"ABBRUCH: {len(teile)}/3 Bausteine in backend/llm.py gefunden")
    sys.exit(2)
ns = {}
exec("\n".join(teile), ns)
kappen = ns["werkzeug_ergebnis_kappen"]
MAX = ns["PROMPT_WERKZEUG_MAX"]

# Echter H8-Rahmen (das Modul hat keine schweren Abhaengigkeiten)
sys.path.insert(0, str(ROOT))
try:
    from backend import werkzeug_rahmen as wr
except Exception as ex:  # noqa: BLE001
    print(f"ABBRUCH: werkzeug_rahmen nicht ladbar: {ex}")
    sys.exit(2)

print("\n1. Unter der Grenze: unveraendert")
kurz = wr.rahmen("knowledge_search", "kurzer Inhalt", "abc123")
check("kurzer Text kommt byte-gleich zurueck", kappen(kurz) == kurz)
check("genau an der Grenze: unveraendert", kappen("x" * MAX) == "x" * MAX)
check("None wird zu Leerstring", kappen(None) == "")

print("\n2. Ueber der Grenze: beziffert, Ende bleibt")
lang = wr.rahmen("knowledge_search", "A" * 2000 + "MITTE" * 2000 + "Z" * 2000, "k9k9k9")
aus = kappen(lang)
endzeile = lang.strip().splitlines()[-1]
check("Positivkontrolle: der Testrahmen ist laenger als die Grenze", len(lang) > MAX,
      str(len(lang)))
check("Positivkontrolle: Endzeile ist die H8-Endmarke", wr.ENDE in endzeile, endzeile)
check("⚠ der Hinweis steht VORN", aus.startswith("[GEKÜRZT:"), aus[:60])
check("… und beziffert gezeigte und gesamte Zeichen",
      f"{MAX} von {len(lang)} Zeichen" in aus.splitlines()[0], aus.splitlines()[0])
check("⚠ die Rahmen-Endzeile ist erhalten", aus.rstrip().endswith(endzeile),
      aus[-120:])
check("der Rahmenkopf (Anfang) ist erhalten", lang[:80] in aus)
check("eine Auslassungsmarke steht in der Mitte", "Zeichen ausgelassen" in aus)
check("die Laenge bleibt begrenzt (Grenze + Hinweise < Grenze + 300)",
      len(aus) < MAX + 300, str(len(aus)))
check("kleine Grenze: Ende nimmt hoechstens ein Drittel",
      kappen("a" * 50 + "E" * 50, grenze=30).endswith("E" * 10))

print("\n3. Regel: kein stilles Slicing mehr an Werkzeugergebnissen")
fstrings = []
for knoten in ast.walk(baum):
    if isinstance(knoten, ast.JoinedStr):
        roh = ast.get_source_segment(src, knoten) or ""
        if "Tool-Ergebnis" in roh:
            fstrings.append(knoten)
check("Positivkontrolle: die Werkzeugergebnis-Nachricht ist auffindbar", len(fstrings) >= 1,
      str(len(fstrings)))
gefunden_kappstelle = False
for f in fstrings:
    aufrufe = [v.value for v in f.values if isinstance(v, ast.FormattedValue)]
    slice_ = any(isinstance(a, ast.Subscript) and isinstance(a.slice, ast.Slice)
                 for a in aufrufe)
    kappt = any(isinstance(a, ast.Call) and getattr(a.func, "id", "") == "werkzeug_ergebnis_kappen"
                for a in aufrufe)
    zeile = f.lineno
    # Jede Stelle: kein stilles Slicing. Die Prompt-Werkzeugmodus-Stelle
    # ("Tool-Ergebnis für") ist die, die kappen MUSS (kleine Kontexte);
    # _build_followup reicht das Ergebnis ungekuerzt durch – auch das ist ehrlich.
    check(f"Zeile {zeile}: kein Slice im Platzhalter", not slice_)
    if "Tool-Ergebnis für" in (ast.get_source_segment(src, f) or ""):
        check(f"Zeile {zeile}: Prompt-Werkzeugmodus geht durch werkzeug_ergebnis_kappen", kappt)
        gefunden_kappstelle = True

check("Positivkontrolle: die kappende Stelle wurde geprueft", gefunden_kappstelle)

print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
