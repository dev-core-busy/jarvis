#!/usr/bin/env python3
"""Waechter: MCP-Aufrufe ohne Pflichtangaben oder mit Schema-Beispielwerten
gehen NICHT zur Bestaetigungskarte, sondern mit Grund ans Modell zurueck.

⚠ WARUM (DEV 2026-10-25): "liefere eine Befundliste vom Typ LDT3.2.18 der
letzten 5 Tage fuer theben an IP …" – das Modell rief
``mcp_theben_list_befunde`` mit ``lab_code: "an1"`` (das Beispiel aus der
Schema-Beschreibung "Laborcode, z.B. 'an1'") und ohne das Pflichtfeld
``port``. Die Karte zeigte den erfundenen Laborcode zur Freigabe.

Gemessen wird die WIRKUNG (`_mcp_argumente_pruefen` wird ausgefuehrt, mit dem
echten Schema-Aufbau von theben) und als REGEL am Syntaxbaum: die Pruefung
steht im Dispatch VOR `_wirkung.freigabe`, und beide Laufarten setzen die
Benutzereingabe.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    python3 tests/test_mcp_argumente.py
"""
import ast
import contextvars
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_SRC = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


def _hol(pattern, was):
    m = re.search(pattern, AGENT_SRC, re.S)
    if not m:
        print(f"ABBRUCH: {was} nicht gefunden – gegen diesen Stand nicht lauffaehig.",
              file=sys.stderr)
        sys.exit(2)
    return m.group(0)


# ── Funktionen aus agent.py schneiden (ohne den schweren Import) ────────────
ns = {"re": re, "contextvars": contextvars}
exec(_hol(r'\nINTERNE_VERLAUFS_MARKEN = .*?(?=\n_BLOCKED_TOOLS_FOR_LDAP)',
          "ist_benutzerfrage"), ns)
exec(_hol(r'\n_benutzer_eingabe_cv: .*?\)\n', "_benutzer_eingabe_cv"), ns)
exec(_hol(r'\n# ── MCP-Argumente: .*?(?=\ndef _reminder_exempt)', "MCP-Argument-Block"), ns)
pruefen = ns["_mcp_argumente_pruefen"]
cv = ns["_benutzer_eingabe_cv"]


class Tool:
    def __init__(self, schema):
        self._s = schema

    def parameters_schema(self):
        return self._s


# Aufbau wie theben/list_befunde (tools/list auf DEV 2026-10-25), Adresse
# durch einen Dokumentations-Platzhalter ersetzt.
THEBEN = Tool({
    "type": "object",
    "properties": {
        "lab_code": {"type": "string", "description": "Laborcode, z.B. 'an1'"},
        "host": {"type": "string",
                 "description": "Ziel-IP der Theben-Datenbank, z.B. '192.0.2.5'"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535,
                 "description": "Zielport der Theben-Datenbank, z.B. 3306"},
        "days": {"type": "integer", "minimum": 0,
                 "description": "Zeitraum in Tagen rückwärts nach Eingangsdatum; "
                                "0 = nur heute. Standard: 5"},
        "ldt_version": {"type": "string",
                        "description": "Optional: nur Befunde dieser LDT-Version bzw. "
                                       "dieses Typs, genau wie in Theben gespeichert, "
                                       "z.B. 'LDT3.2.19', 'LDT1014.01' oder 'hl7'. "
                                       "Ohne Angabe alle Versionen."},
    },
    "required": ["lab_code", "host", "port"],
})

AUFTRAG = ("liefere eine Befundliste vom Typ LDT3.2.18 der letzten 5 Tage fuer "
           "theben an IP 198.51.100.7 als csv")


def mit_eingabe(text, verlauf=None):
    return cv.set({"text": text, "verlauf": verlauf})


# ── Positivkontrolle: die Beispiel-Erkennung sieht ueberhaupt etwas ─────────
bsp = ns["_schema_beispiele"](THEBEN._s["properties"]["lab_code"])
if bsp != {"an1"}:
    print(f"ABBRUCH: Beispiel-Erkennung blind (lab_code -> {bsp!r}).", file=sys.stderr)
    sys.exit(2)

print("1. Der gemeldete Fall")
tok = mit_eingabe(AUFTRAG)
grund = pruefen(THEBEN, {"days": 5, "host": "198.51.100.7", "lab_code": "an1",
                         "ldt_version": "LDT3.2.18"})
check(grund is not None, "Aufruf aus dem Vorfall wird zurueckgewiesen")
g = grund or ""
check("'port'" in g and "Pflicht" in g, "fehlendes Pflichtfeld 'port' wird genannt")
check("'lab_code' = 'an1'" in g and "BEISPIEL" in g, "'an1' wird als Schema-Beispiel benannt")
check("Frage den Benutzer" in g, "Grund nennt den Weg (Benutzer fragen)")
cv.reset(tok)

print("2. Was NICHT abgewiesen werden darf")
tok = mit_eingabe(AUFTRAG + ", Labor an1, Port 3306")
check(pruefen(THEBEN, {"days": 5, "host": "198.51.100.7", "lab_code": "an1",
                       "port": 3306, "ldt_version": "LDT3.2.18"}) is None,
      "Beispielwerte, die der Benutzer SELBST nennt, gehen durch")
cv.reset(tok)
tok = mit_eingabe("und jetzt 10 Tage",
                  verlauf=[types.SimpleNamespace(role="user", parts=[
                      types.SimpleNamespace(text="Labor AN1 an 198.51.100.7:3306",
                                            function_response=None, inline_data=None)])])
check(pruefen(THEBEN, {"days": 10, "host": "198.51.100.7", "lab_code": "an1",
                       "port": 3306}) is None,
      "Angabe aus einer FRUEHEREN Benutzerfrage zaehlt (Gross/Klein egal)")
cv.reset(tok)
tok = mit_eingabe(AUFTRAG + " Labor ab1 Port 3307")
check(pruefen(THEBEN, {"host": "198.51.100.7", "lab_code": "ab1", "port": 3307}) is None,
      "Nicht-Beispielwerte gehen durch")
check(pruefen(THEBEN, {"host": "198.51.100.7", "lab_code": "ab1", "port": 3307,
                       "days": 5}) is None,
      "'Standard: 5' ist eine Vorgabe, kein Beispiel")
cv.reset(tok)

print("3. Was trotzdem abgewiesen wird")
tok = mit_eingabe("Befunde fuer plan1",
                  verlauf=[types.SimpleNamespace(role="user", parts=[
                      types.SimpleNamespace(text="Laborcode, z.B. 'an1'",
                                            function_response=object(), inline_data=None)])])
check(pruefen(THEBEN, {"host": "x", "lab_code": "an1", "port": 1}) is not None,
      "Beispiel im WERKZEUG-Ergebnis oder als Wortteil ('plan1') zaehlt nicht")
cv.reset(tok)
tok = mit_eingabe(AUFTRAG + " Labor ab1")
check(pruefen(THEBEN, {"host": "198.51.100.7", "lab_code": "ab1", "port": 3306}) is not None,
      "Port-Beispiel 3306 ohne Benutzerangabe wird abgewiesen")
check(pruefen(THEBEN, {"host": "198.51.100.7", "lab_code": "", "port": 5}) is not None,
      "leeres Pflichtfeld zaehlt als fehlend")
cv.reset(tok)
check(pruefen(THEBEN, {"host": "h", "port": 1}) is not None,
      "ohne Laufkontext: fehlendes Pflichtfeld wird trotzdem gemeldet")
check(pruefen(THEBEN, {"host": "h", "lab_code": "an1", "port": 1}) is None,
      "ohne Laufkontext (unbekannt): Beispielpruefung uebersprungen, nicht alles gesperrt")

# ── Regeln am Syntaxbaum ────────────────────────────────────────────────────
print("4. Verdrahtung")
baum = ast.parse(AGENT_SRC)
fn = {n.name: n for n in ast.walk(baum)
      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for pflicht in ("_execute_tool", "run_task", "_run_headless"):
    if pflicht not in fn:
        print(f"ABBRUCH: {pflicht} fehlt in agent.py.", file=sys.stderr)
        sys.exit(2)


def _aufrufe(knoten, name):
    aus = []
    for n in ast.walk(knoten):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if nm == name:
                aus.append(n)
    return aus


ex = fn["_execute_tool"]
pr = _aufrufe(ex, "_mcp_argumente_pruefen")
fg = _aufrufe(ex, "freigabe")
check(len(pr) == 1, "_execute_tool ruft _mcp_argumente_pruefen genau einmal")
check(bool(pr) and bool(fg) and max(c.lineno for c in pr) < min(c.lineno for c in fg),
      "die Pruefung steht VOR der Bestaetigungskarte (_wirkung.freigabe)")
for lauf in ("run_task", "_run_headless"):
    sets = [c for c in _aufrufe(fn[lauf], "set")
            if isinstance(c.func, ast.Attribute)
            and getattr(c.func.value, "id", None) == "_benutzer_eingabe_cv"]
    check(bool(sets), f"{lauf} setzt die Benutzereingabe des Laufs")

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
