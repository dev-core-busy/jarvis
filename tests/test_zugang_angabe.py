#!/usr/bin/env python3
"""
Waechter: die Fachproben-Endpunkte sagen, MIT WELCHEM Zugang sie antworten
(Vorgabe 2026-11-16).

ANLASS: /api/confluence/spaces, /api/jira/search, /api/sap/odata/services,
/api/sap/tables und /api/vemas/query fallen still auf den gemeinsamen Zugang
zurueck, wenn der eigene nicht greift. Die Fachprobe in "Mein …-Zugang"
meldete dann "funktioniert", obwohl der eigene Zugang gar nicht benutzt
wurde. Jede Antwort traegt deshalb ``zugang`` ({quelle, hinweis}).

GEMESSEN (am Syntaxbaum bzw. ausgefuehrt, nicht am Text):
  1. Positivkontrolle: alle fuenf Endpunkte und der Helfer sind gefunden
     (sonst Exit 2 – eine Regel ueber null Funktionen waere trivial wahr).
  2. JEDE ``JSONResponse({...})`` dieser Endpunkte hat den Schluessel
     "zugang" – auch die Fehlerwege: "dein Zugang funktioniert nicht" braucht
     die Angabe gerade dort. Eine kuenftige Rueckgabe ohne ihn faellt auf.
  3. ``_zugang_angabe`` wird AUSGEFUEHRT: es gibt NUR quelle und hinweis
     heraus – kein Token, kein Client, kein Benutzer (der Wert geht an den
     Browser). Unbekanntes -> None.
  4. ``client_fuer_lauf`` in confluence_accounts UND jira_accounts haengt
     ``zugang`` an den Client (sonst bliebe das Feld bei diesen beiden still
     None, und die Oberflaeche behauptete nichts – kein Fehler, aber die
     Zusage waere weg).

Aufruf: python3 tests/test_zugang_angabe.py   Exit 0 gruen, 1 FAIL, 2 kaputt
"""
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = Path(os.environ.get("ZUGANG_MAIN") or ROOT / "backend" / "main.py")
KONTEN = {
    "confluence": Path(os.environ.get("ZUGANG_CONF") or ROOT / "backend" / "confluence_accounts.py"),
    "jira": Path(os.environ.get("ZUGANG_JIRA") or ROOT / "backend" / "jira_accounts.py"),
}
ENDPUNKTE = ["confluence_spaces_api", "jira_search_api", "sap_odata_services_api",
             "sap_tables_api", "vemas_query"]

OK = FAIL = 0


def check(bed, name, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{info}]" if info else ""))


def funktionen(baum):
    return {n.name: n for n in ast.walk(baum)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


baum = ast.parse(MAIN.read_text(encoding="utf-8"))
fn = funktionen(baum)

print("\n═══ 1) Positivkontrolle")
# Nur fehlende ENDPUNKTE sind ein kaputter Messaufbau (Exit 2). Ein fehlender
# HELFER ist ein Produktbefund und wird als FAIL gemeldet – sonst saehe der
# Altstand wie "konnte nicht laufen" aus statt wie ein Biss (Register).
fehlt = [n for n in ENDPUNKTE if n not in fn]
if fehlt:
    print(f"ABBRUCH: Endpunkte nicht gefunden: {fehlt}")
    sys.exit(2)
check(True, "alle fuenf Endpunkte gefunden")
check("_zugang_angabe" in fn, "Helfer _zugang_angabe vorhanden")

print("\n═══ 2) Jede Antwort der Endpunkte traegt 'zugang'")
for name in ENDPUNKTE:
    antworten = [c for c in ast.walk(fn[name])
                 if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "JSONResponse"
                 and c.args and isinstance(c.args[0], ast.Dict)]
    ohne = [c.lineno for c in antworten
            if not any(isinstance(k, ast.Constant) and k.value == "zugang" for k in c.args[0].keys)]
    check(len(antworten) > 0, f"{name}: hat Antworten (Positivkontrolle)", str(len(antworten)))
    check(not ohne, f"{name}: alle {len(antworten)} Antworten tragen 'zugang'",
          f"ohne in Zeile(n) {ohne}")
    # Der Wert kommt aus _zugang_angabe – nicht aus einem handgebauten dict,
    # das beim naechsten Feld (z. B. benutzer) mehr herausgaebe.
    ruft = any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_zugang_angabe"
               for c in ast.walk(fn[name]))
    check(ruft, f"{name}: Wert kommt aus _zugang_angabe")

print("\n═══ 3) _zugang_angabe gibt NUR quelle und hinweis heraus")
ns = {}
if "_zugang_angabe" in fn:
    exec(compile(ast.Module(body=[fn["_zugang_angabe"]], type_ignores=[]), str(MAIN), "exec"), ns)
f = ns.get("_zugang_angabe") or (lambda z: {"fehlt": True})
voll = {"client": object(), "quelle": "persoenlich", "hinweis": "h",
        "benutzer": "anna", "api_token": "GEHEIM", "token": "GEHEIM"}
r = f(voll)
check(isinstance(r, dict) and set(r) == {"quelle", "hinweis"},
      "nur die Schluessel quelle und hinweis", repr(r))
check(r == {"quelle": "persoenlich", "hinweis": "h"}, "Werte korrekt uebernommen", repr(r))
check("GEHEIM" not in repr(r) and "anna" not in repr(r), "kein Token, kein Benutzer in der Angabe")
check(f({"quelle": None}) == {"quelle": "", "hinweis": ""}, "None wird zu Leertext")
check(f(None) is None and f("persoenlich") is None, "Unbekanntes -> None")

print("\n═══ 4) client_fuer_lauf haengt 'zugang' an den Client")
for bereich, pfad in KONTEN.items():
    kfn = funktionen(ast.parse(pfad.read_text(encoding="utf-8"))).get("client_fuer_lauf")
    check(kfn is not None, f"{bereich}: client_fuer_lauf gefunden")
    if kfn is None:
        continue
    setzt = [n for n in ast.walk(kfn) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Attribute) and t.attr == "zugang" for t in n.targets)]
    check(bool(setzt), f"{bereich}: setzt <client>.zugang")
    ruft = any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "aufloesen"
               for c in ast.walk(kfn))
    check(ruft, f"{bereich}: Angabe stammt aus aufloesen()")

print(f"\nERGEBNIS: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
