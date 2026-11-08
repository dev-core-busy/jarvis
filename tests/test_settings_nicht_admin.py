#!/usr/bin/env python3
"""Waechter: ``GET /api/settings`` und ``GET /api/profiles`` verraten
Nicht-Administratoren keine Profil-Interna.

Befund (Pentest-Vorbereitung 2026-11-05): beide Routen haengen an
``require_auth`` und lieferten jedem Benutzer alle LLM-Profile mit
``api_url``, ``allowed_users``/``allowed_group`` und den letzten vier Zeichen
der API-Schluessel, dazu den maskierten ``agent_api_key``.

Gemessen wird die WIRKUNG: ``_settings_nicht_admin`` und ``_profil_kurz``
werden aus main.py geschnitten (AST, ohne den echten Import, der
``backend.config`` laden wuerde) und mit Profilen ausgefuehrt, die echte
Geheimnis- und Freigabefelder tragen. Dazu die Regel am Syntaxbaum: beide
Routen beginnen mit dem Nicht-Admin-Zweig, und der antwortet ueber
``_settings_nicht_admin``.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(SRC)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}" + (f"  -> {detail}" if detail else ""))


def funktion(name):
    for n in BAUM.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


ns = {}
for name in ("_profil_kurz", "_settings_nicht_admin"):
    fn = funktion(name)
    if fn is None:
        print(f"ABBRUCH: {name} nicht in main.py")
        sys.exit(2)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "main.py", "exec"), ns)

SCHLUESSEL = "sk-SONDE-abcdefgh1234"
PROFILE = [
    {"id": "p1", "name": "Erlaubt", "provider": "openai", "model": "m1",
     "api_url": "https://llm.beispiel.de/v1", "api_key": SCHLUESSEL,
     "session_key": "SONDE-SESSION-9876", "allowed_users": ["sonde.benutzer"],
     "allowed_group": "SONDE-GRUPPE"},
    {"id": "p2", "name": "Aktiv-gesperrt", "provider": "anthropic", "model": "m2",
     "api_url": "https://llm2.beispiel.de", "api_key": SCHLUESSEL,
     "allowed_users": ["jemand.anderes"]},
    {"id": "p3", "name": "Fremd", "provider": "x", "model": "m3",
     "api_url": "https://geheim.beispiel.de", "api_key": SCHLUESSEL},
]


class Cfg:
    profiles = PROFILE
    TTS_ENABLED = True
    TTS_VOICE = "sonde-stimme"
    AGENT_API_KEY = "SONDE-AGENTKEY-5555"


antwort = ns["_settings_nicht_admin"](Cfg(), lambda p: p["id"] == "p1", "p2")
text = json.dumps(antwort)

# Positivkontrolle: die Funktion hat wirklich Profile verarbeitet
if not isinstance(antwort, dict) or not antwort.get("profiles"):
    print(f"ABBRUCH: Positivkontrolle – keine Profile in der Antwort ({antwort!r})")
    sys.exit(2)

print("── 1. Wirkung ──")
for verboten in ("1234", "9876", "llm.beispiel.de", "llm2.beispiel.de", "sonde.benutzer",
                 "SONDE-GRUPPE", "5555", "allowed_", "api_url", "api_key", "session_key",
                 "agent_api_key", "defaults"):
    check(f"Antwort enthaelt kein '{verboten}'", verboten not in text)
ids = [p.get("id") for p in antwort["profiles"]]
check("erlaubtes Profil ist dabei", "p1" in ids, str(ids))
check("aktives (gesperrtes) Profil ist dabei", "p2" in ids, str(ids))
check("fremdes, nicht erlaubtes Profil fehlt", "p3" not in ids, str(ids))
check("TTS-Felder bleiben (chat.js braucht sie)",
      antwort.get("tts_enabled") is True and antwort.get("tts_voice") == "sonde-stimme")
check("aktive Profil-ID ist die des Benutzers", antwort.get("active_profile_id") == "p2")

print("── 2. Routen ──")


def nicht_admin_zweig(route_name):
    fn = funktion(route_name)
    if fn is None:
        return None, "Route fehlt"
    rumpf = [s for s in fn.body if not (isinstance(s, ast.Expr)
                                         and isinstance(getattr(s, "value", None), ast.Constant))]
    erste = rumpf[0] if rumpf else None
    if not isinstance(erste, ast.If):
        return False, "erste Anweisung ist kein if"
    t = erste.test
    bed = (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
           and isinstance(t.operand, ast.Call) and getattr(t.operand.func, "id", "") == "_user_is_admin"
           and t.operand.args and getattr(t.operand.args[0], "id", "") == "user")
    if not bed:
        return False, "Bedingung ist nicht 'not _user_is_admin(user)'"
    hat_return = any(isinstance(x, ast.Return) for x in erste.body)
    ruft = any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_settings_nicht_admin"
               for c in ast.walk(erste))
    return (hat_return and ruft), f"return={hat_return} ruft={ruft}"


for r in ("get_settings", "get_profiles"):
    erg, det = nicht_admin_zweig(r)
    if erg is None:
        print(f"ABBRUCH: {r}: {det}")
        sys.exit(2)
    check(f"{r}: Nicht-Admin-Zweig vorn und ueber _settings_nicht_admin", erg, det)

print(f"\nBilanz: {ok} OK, {fail} FAIL")
sys.exit(0 if fail == 0 else 1)
