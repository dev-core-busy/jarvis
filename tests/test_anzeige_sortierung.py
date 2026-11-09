#!/usr/bin/env python3
"""Waechter: Auswahllisten mit Benutzern/Adressen stehen alphabetisch.

GEMELDET 2026-11-09: *Einstellungen → Fehleranalyse → Benutzer* war unsortiert.
Die Quelle (``conv_log.get_known_users``) liefert die Reihenfolge der letzten
Aktivitaet. Dieselbe Herkunft hatten der Benutzer- und der IP-Filter im Verlauf
(Telemetrie) und der Benutzerfilter der Zugriffs-Verstoesse.

Gemessen wird zweierlei:
1. ``backend/anzeige_sortierung.py`` WIRKLICH ausgefuehrt – Eingaben in
   Aktivitaetsreihenfolge, Ausgabe gegen die erwartete Folge.
2. Am Syntaxbaum von ``main.py``: die Rueckgabe der Endpunkte geht durch den
   Sortierer, und zwar NACH der Namensaufbereitung (``_mit_anzeigenamen`` ist
   das ARGUMENT des Sortierers, nicht umgekehrt). Ein Vorkommen des Namens
   irgendwo im Rumpf genuegt nicht (Register: „ein Waechter, der ein
   Vorkommen prueft, misst keine Wirkung").

    python3 tests/test_anzeige_sortierung.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


try:
    from backend import anzeige_sortierung as S
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.anzeige_sortierung nicht ladbar: {e}")
    sys.exit(2)

MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
try:
    BAUM = ast.parse(MAIN)
except SyntaxError as e:
    print(f"ABBRUCH: main.py nicht parsebar: {e}")
    sys.exit(2)

FUNKTIONEN = {n.name: n for n in ast.walk(BAUM)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

# ── Positivkontrolle ─────────────────────────────────────────────────────
# Die Probe muss UNSORTIERT hineingehen, sonst ist jede Pruefung darunter
# trivial wahr (eine Funktion, die nichts tut, bestuende sie).
print("\n=== 0. Positivkontrolle ===")
AKTIVITAET = ["contoso\\m.wolf", "jarvis", "contoso\\a.klein", "contoso\\Ä.berg",
              "contoso\\user10", "contoso\\user2", "api"]
# "Ä.berg" zaehlt als "a.berg" und steht damit VOR "a.klein" – nach Codepunkt
# stuende es hinter allem (Ä = U+00C4).
ERWARTET = ["api", "contoso\\Ä.berg", "contoso\\a.klein", "contoso\\m.wolf",
            "contoso\\user2", "contoso\\user10", "jarvis"]
if AKTIVITAET == sorted(AKTIVITAET) or AKTIVITAET == ERWARTET:
    print("ABBRUCH: die Probe ist schon sortiert – sie misst nichts")
    sys.exit(2)
for name in ("api_conv_log_users", "api_conv_log_ips", "security_violations",
             "userchat_known_users"):
    if name not in FUNKTIONEN:
        print(f"ABBRUCH: Endpunkt {name} nicht in main.py gefunden – "
              "umbenannt? Dann den Waechter nachziehen.")
        sys.exit(2)

# ── 1. Modul ─────────────────────────────────────────────────────────────
print("\n=== 1. namen_sortiert ===")
erg = S.namen_sortiert(AKTIVITAET)
pruefe(erg == ERWARTET, "Aktivitaetsreihenfolge wird alphabetisch", f"{erg}")
pruefe(S.namen_sortiert(["b", "A", "a", "C"]) == ["A", "a", "b", "C"],
       "Gross/Klein entscheidet nicht (feste Folge bei Gleichstand)",
       f"{S.namen_sortiert(['b', 'A', 'a', 'C'])}")
pruefe(S.namen_sortiert(["Zander", "Ärger", "Bauer"]) == ["Ärger", "Bauer", "Zander"],
       "Umlaut zaehlt wie der Grundbuchstabe (Ä bei A, nicht hinter Z)",
       f"{S.namen_sortiert(['Zander', 'Ärger', 'Bauer'])}")
pruefe(S.namen_sortiert(["user10", "user9", "user1"]) == ["user1", "user9", "user10"],
       "Ziffernfolgen numerisch (user9 vor user10)",
       f"{S.namen_sortiert(['user10', 'user9', 'user1'])}")
pruefe(S.namen_sortiert(["x", "x", "", "  ", None, "a"]) == ["a", "x"],
       "Doppelte und leere Eintraege fallen weg",
       f"{S.namen_sortiert(['x', 'x', '', '  ', None, 'a'])}")
pruefe(S.namen_sortiert([]) == [] and S.namen_sortiert(None) == [],
       "leere Eingabe ergibt leere Liste, ohne Wurf")
try:
    S.namen_sortiert(["a1b", "a01", "ab", "a"])
    pruefe(True, "Text- und Zifferstuecke an gleicher Stelle werfen nicht")
except Exception as e:  # noqa: BLE001
    pruefe(False, "Text- und Zifferstuecke an gleicher Stelle werfen nicht", repr(e))

print("\n=== 2. ips_sortiert ===")
ips = ["10.0.0.10", "unknown", "192.0.2.1", "10.0.0.9", "2001:db8::1", "10.0.0.9"]
erg = S.ips_sortiert(ips)
pruefe(erg == ["10.0.0.9", "10.0.0.10", "192.0.2.1", "2001:db8::1", "unknown"],
       "numerisch, IPv4 vor IPv6, Unbekanntes ans Ende, ohne Doppelte", f"{erg}")


# ── 3. Endpunkte (Syntaxbaum) ────────────────────────────────────────────
def _ist_aufruf(knoten, attr: str) -> bool:
    """``_anzeige_sortierung.<attr>(...)`` – exakt, kein Teilstring."""
    return (isinstance(knoten, ast.Call)
            and isinstance(knoten.func, ast.Attribute)
            and knoten.func.attr == attr
            and isinstance(knoten.func.value, ast.Name)
            and knoten.func.value.id == "_anzeige_sortierung")


def _ist_name_aufruf(knoten, name: str) -> bool:
    return (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name)
            and knoten.func.id == name)


def _rueckgabe_json(fn) -> list:
    """Erstes Argument jedes ``return JSONResponse(...)`` im Rumpf."""
    aus = []
    for r in ast.walk(fn):
        if (isinstance(r, ast.Return) and _ist_name_aufruf(r.value, "JSONResponse")
                and r.value.args):
            aus.append(r.value.args[0])
    return aus


print("\n=== 3. Endpunkte ===")
rueck = _rueckgabe_json(FUNKTIONEN["api_conv_log_users"])
pruefe(len(rueck) == 1 and _ist_aufruf(rueck[0], "namen_sortiert"),
       "/api/conv_log/users gibt namen_sortiert(...) zurueck",
       ast.unparse(rueck[0]) if rueck else "kein return JSONResponse")
pruefe(len(rueck) == 1 and _ist_aufruf(rueck[0], "namen_sortiert")
       and rueck[0].args and _ist_name_aufruf(rueck[0].args[0], "_mit_anzeigenamen"),
       "… und sortiert NACH der Namensaufbereitung",
       ast.unparse(rueck[0]) if rueck else "")

rueck = _rueckgabe_json(FUNKTIONEN["api_conv_log_ips"])
pruefe(len(rueck) == 1 and _ist_aufruf(rueck[0], "ips_sortiert"),
       "/api/conv_log/ips gibt ips_sortiert(...) zurueck",
       ast.unparse(rueck[0]) if rueck else "kein return JSONResponse")

# Verstoesse: ``namen`` wird zugewiesen und im Rueckgabe-Dict als "users"
# ausgeliefert. Gemessen: die EINZIGE Zuweisung an `namen` ist der Sortierer
# ueber die Aufbereitung, und "users" traegt genau diese Variable.
fn = FUNKTIONEN["security_violations"]
zuw = [z for z in ast.walk(fn) if isinstance(z, ast.Assign)
       and any(isinstance(t, ast.Name) and t.id == "namen" for t in z.targets)]
pruefe(len(zuw) == 1 and _ist_aufruf(zuw[0].value, "namen_sortiert")
       and zuw[0].value.args and _ist_name_aufruf(zuw[0].value.args[0], "_mit_anzeigenamen"),
       "Verstoesse: namen = namen_sortiert(_mit_anzeigenamen(...))",
       "; ".join(ast.unparse(z) for z in zuw) or "keine Zuweisung an namen")
nach_namen = [z for z in ast.walk(fn) if isinstance(z, (ast.AugAssign, ast.Expr))
              and isinstance(getattr(z, "value", None), ast.Call)
              and isinstance(z.value.func, ast.Attribute)
              and isinstance(z.value.func.value, ast.Name)
              and z.value.func.value.id == "namen"]
pruefe(not nach_namen, "Verstoesse: namen wird danach nicht mehr umgestellt (append/insert)",
       "; ".join(ast.unparse(z) for z in nach_namen))
users_wert = []
for d in ast.walk(fn):
    if isinstance(d, ast.Dict):
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and k.value == "users":
                users_wert.append(v)
pruefe(len(users_wert) == 1 and isinstance(users_wert[0], ast.Name)
       and users_wert[0].id == "namen",
       "Verstoesse: \"users\" traegt genau die sortierte Liste",
       "; ".join(ast.unparse(v) for v in users_wert) or "kein \"users\"-Schluessel")

# Userchat: Schluessel ist der blosse Kontoname (so zeigt ihn der Chat an),
# nicht der Login mit Praefix.
fn = FUNKTIONEN["userchat_known_users"]
sorts = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
         and isinstance(c.func, ast.Attribute) and c.func.attr == "sort"]
ok_key = False
for c in sorts:
    for kw in c.keywords:
        if kw.arg == "key" and isinstance(kw.value, ast.Lambda):
            for k in ast.walk(kw.value.body):
                if (_ist_aufruf(k, "text_schluessel") and k.args
                        and _ist_name_aufruf(k.args[0], "_norm_login")):
                    ok_key = True
pruefe(ok_key, "Userchat-Liste sortiert nach text_schluessel(_norm_login(...))",
       "; ".join(ast.unparse(c) for c in sorts) or "kein .sort()")

print(f"\n{'=' * 70}")
print(f"Ergebnis: {_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(0 if _fail == 0 else 1)
