#!/usr/bin/env python3
"""Waechter: Programmschluessel (Agent-API-Keys) – Bereiche, Ablauf, Auftraggeber.

Anlass 2026-11-20 (live auf DEV gemessen, tests/live_agent_api_ws_dev.py): ein
Auftrag, der NUR mit Programmschluessel ueber den Chat-WebSocket kam, nahm den
Root-Weg der Shell. Dazu oeffnete jeder Schluessel jeden Schluessel-Weg, ohne
Ablauf.

  1  backend/agent_schluessel.py AUSGEFUEHRT: Pfad → Bereich, Bestand,
     Vorgabe, Ablauf, Kandidaten
  2  REGEL ueber main.py: jeder Endpunkt, der einen Schluessel annimmt, ist
     einem Bereich zugeordnet (sonst nimmt er gar keinen an – fail-closed,
     aber still kaputt)
  3  agent._auftraggeber AUSGEFUEHRT: Hauptagent ohne Namen ist nie
     privilegiert und erbt nichts; Unter-Agenten erben weiter
  4  main.py (AST): Schluessel-Verbindung am WebSocket bekommt den festen
     Auftraggeber; die Pruefung nennt immer einen Bereich

Exit 0 = bestanden, 1 = Befund, 2 = konnte nicht laufen.
    venv/bin/python tests/test_agent_schluessel.py
"""
import ast
import importlib.util
import re
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


spec = importlib.util.spec_from_file_location("aks", ROOT / "backend/agent_schluessel.py")
aks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aks)

# ═══════════════════════════════════════════════════════════════════════════
print("\n1. agent_schluessel")
# ═══════════════════════════════════════════════════════════════════════════
faelle = {
    "/api/agent/task": "agent", "/ws": "chat", "/api/download-key": "dateien",
    "/api/documents/x.pdf": "dateien", "/api/generated/a.png": "dateien",
    "/api/knowledge/file_read": "dateien", "/api/knowledge/file_raw": "dateien",
    "/api/issues": "issues", "/api/issues/7/attachments/a.txt": "issues",
    "/api/jira/phonenumber": "jira", "/api/avatar/ask": "sprache", "/api/tts": "sprache",
    "/api/tts/voices": "sprache", "/api/support/query": "support", "/api/feedback": "feedback",
}
for pfad, soll in faelle.items():
    check(aks.bereich_fuer_pfad(pfad) == soll, f"{pfad} → {soll}", aks.bereich_fuer_pfad(pfad))
for pfad in ("/wsx", "/api/issuesx", "/api/ttsfoo", "/api/knowledge/search",
             "/api/agent/taskx", "/api/settings", "/", ""):
    check(aks.bereich_fuer_pfad(pfad) == "", f"{pfad!r} hat KEINEN Bereich (Grenze/Praefix)",
          aks.bereich_fuer_pfad(pfad))
check(aks.bereiche_von({"key": "k"}) == aks.BESTAND, "Bestand ohne Feld: alle Bestands-Bereiche")
check(aks.bereiche_von({"key": "k", "bereiche": ["agent", "x"]}) == ("agent",),
      "unbekannte Bereiche im Feld fallen heraus")
check(aks.bereiche_von({"key": "k", "bereiche": "agent"}) == (), "kaputtes Feld: nichts")
check(aks.VORGABE == ("agent",), "Vorgabe fuer neue Schluessel: nur Agent-Auftraege")

heute = time.strftime("%Y-%m-%d")
check(not aks.abgelaufen({"ablauf": heute}), "gilt bis Ende des Ablauftages")
check(aks.abgelaufen({"ablauf": "2020-01-01"}), "vergangenes Datum: abgelaufen")
check(not aks.abgelaufen({"ablauf": ""}), "leer: unbefristet")
check(aks.abgelaufen({"ablauf": "morgen"}), "unlesbares Datum: abgelaufen (fail-closed)")
check(aks.ablauf_pruefen("2026-13-40")[1] != "", "ungueltiges Datum wird abgelehnt")
check(aks.bereiche_pruefen(["agent", "root"])[1] != "", "unbekannter Bereich wird abgelehnt")

E = [{"key": "A", "bereiche": ["agent"]}, {"key": "B"},
     {"key": "C", "bereiche": ["agent", "dateien"], "ablauf": "2020-01-01"}]
check(aks.kandidaten(E, "L", "agent") == ["L", "A", "B"], "Bereich agent: Legacy, A, Bestand B",
      str(aks.kandidaten(E, "L", "agent")))
check(aks.kandidaten(E, "L", "dateien") == ["L", "B"], "Bereich dateien: A nicht, C abgelaufen",
      str(aks.kandidaten(E, "L", "dateien")))
check(aks.kandidaten(E, "L", "") == [], "Pfad ohne Bereich: KEIN Schluessel")
check("C" not in aks.kandidaten(E, "L", None), "abgelaufener Schluessel auch ohne Bereich ungueltig")

# ═══════════════════════════════════════════════════════════════════════════
print("\n2. REGEL: jeder Schluessel-Endpunkt hat einen Bereich")
# ═══════════════════════════════════════════════════════════════════════════
QUELLE = (ROOT / "backend/main.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
SCHLUESSEL_DEPS = {"require_auth_or_agent", "require_jira_daten_access", "require_auth_or_query"}
SCHLUESSEL_RUFE = {"_verify_agent_api_key", "_sitzung_oder_schluessel", "_is_valid_agent_key"}


def routen(fn):
    raus = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app" \
                and d.args and isinstance(d.args[0], ast.Constant):
            raus.append(str(d.args[0].value))
    return raus


def nimmt_schluessel(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name in SCHLUESSEL_RUFE:
                return True
            if name == "Depends" and n.args and isinstance(n.args[0], ast.Name) \
                    and n.args[0].id in SCHLUESSEL_DEPS:
                return True
    return False


gefunden = []
for fn in BAUM.body:
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and routen(fn) and nimmt_schluessel(fn):
        for r in routen(fn):
            gefunden.append(r)
if len(gefunden) < 25:
    abbruch(f"nur {len(gefunden)} Schluessel-Endpunkte gefunden – die Sonde ist blind")
print(f"  ({len(gefunden)} Endpunkte nehmen einen Schluessel an)")
ohne = [r for r in gefunden
        if not aks.bereich_fuer_pfad(re.sub(r"\{[^}]+\}", "beispiel", r))]
check(not ohne, "jeder Schluessel-Endpunkt ist einem Bereich zugeordnet", ", ".join(ohne))

# ═══════════════════════════════════════════════════════════════════════════
print("\n3. agent._auftraggeber")
# ═══════════════════════════════════════════════════════════════════════════
try:
    from backend import agent as A          # noqa: E402
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.agent nicht ladbar ({e!r}) – mit venv/bin/python starten")
f = A._auftraggeber
haupt = types.SimpleNamespace(is_sub_agent=False, _current_username="jarvis")
check(f(haupt, "") == ("", False), "Hauptagent ohne Namen: nicht privilegiert, erbt 'jarvis' NICHT",
      str(f(haupt, "")))
haupt2 = types.SimpleNamespace(is_sub_agent=False)
check(f(haupt2, "") == ("", False), "frischer Hauptagent ohne Namen: nicht privilegiert",
      str(f(haupt2, "")))
check(f(haupt2, "jarvis") == ("jarvis", True), "Positivkontrolle: 'jarvis' ist privilegiert")
check(f(haupt2, "max.muster") == ("max.muster", False), "Domaenenbenutzer: nicht privilegiert")
check(f(haupt2, "api:schluessel") == ("api:schluessel", False),
      "Schluessel-Auftraggeber: nicht privilegiert")
sub = types.SimpleNamespace(is_sub_agent=True, _current_username="max.muster",
                            _current_actor_privileged=False)
check(f(sub, "") == ("max.muster", False), "Unter-Agent erbt Namen und Privileg des Erzeugers",
      str(f(sub, "")))

# Beide Stellen benutzen DIESELBE Herleitung (Huelle und run_task)
QA = (ROOT / "backend/agent.py").read_text(encoding="utf-8")
BA = ast.parse(QA)
rufe = [n for n in ast.walk(BA) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_auftraggeber"]
check(len(rufe) == 2, "_auftraggeber wird an genau zwei Stellen gerufen (Huelle + run_task)",
      str(len(rufe)))
rt = next((n for n in ast.walk(BA) if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_task"), None)
if rt is None:
    abbruch("run_task nicht gefunden")
zuw = [n for n in ast.walk(rt) if isinstance(n, ast.Assign)
       and any(isinstance(t, ast.Name) and t.id == "_lauf_privilegiert" for t in n.targets)]
check(len(zuw) == 1 and isinstance(zuw[0].value, ast.Name) and zuw[0].value.id == "_ag_priv",
      "run_task: _lauf_privilegiert kommt aus _auftraggeber",
      ast.unparse(zuw[0].value) if zuw else "fehlt")

# ═══════════════════════════════════════════════════════════════════════════
print("\n4. main.py: Chat-WebSocket mit Schluessel")
# ═══════════════════════════════════════════════════════════════════════════
konst = next((n for n in BAUM.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "WS_SCHLUESSEL_AKTEUR" for t in n.targets)), None)
wert = konst.value.value if konst is not None and isinstance(konst.value, ast.Constant) else None
check(isinstance(wert, str) and ":" in wert and wert not in A._LOCAL_PRIVILEGED_USERS,
      "fester Auftraggeber ist kein Login-Name und nicht privilegiert", repr(wert))
hwm = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "handle_ws_message"), None)
if hwm is None:
    abbruch("handle_ws_message nicht gefunden")
zweig = [n for n in ast.walk(hwm) if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
         and n.test.id == "is_api_key"]
setzt = any(isinstance(z, ast.Assign) and isinstance(z.value, ast.Name)
            and z.value.id == "WS_SCHLUESSEL_AKTEUR"
            and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                    and t.value.id == "_ws_usernames" for t in z.targets)
            for zw in zweig for z in ast.walk(zw))
check(setzt, "Zweig 'is_api_key' setzt den festen Auftraggeber in _ws_usernames")
alle = [n for n in ast.walk(BAUM) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_is_valid_agent_key"]
check(len(alle) >= 3 and all(len(n.args) + len(n.keywords) == 2 for n in alle),
      "jeder Aufruf von _is_valid_agent_key nennt einen Bereich",
      str([ast.unparse(n) for n in alle if len(n.args) + len(n.keywords) != 2]))
ws_ruf = [n for n in ast.walk(hwm) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
          and n.func.id == "_is_valid_agent_key"]
check(len(ws_ruf) == 1 and isinstance(ws_ruf[0].args[-1], ast.Constant)
      and ws_ruf[0].args[-1].value == "chat", "der WebSocket prueft den Bereich 'chat'")
ver = next((n for n in BAUM.body if isinstance(n, ast.FunctionDef) and n.name == "_verify_agent_api_key"), None)
check(ver is not None and "url" not in {a.attr for a in ast.walk(ver) if isinstance(a, ast.Attribute)},
      "_verify_agent_api_key liest den Pfad nicht aus request.url (BadHost)")

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
