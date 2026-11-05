#!/usr/bin/env python3
"""Waechter: die IBS-Quelle unter /support haengt am Skill 'Kundenverwaltung'.

Der Server darf bei deaktiviertem Skill keine IBS-Suche starten, auch wenn ein
Aufrufer ``ibs: true`` schickt: Das Ausblenden in der Oberflaeche sperrt die API
nicht. Die Pruefungen fuehren den echten Status-Endpunkt und die echte Bedingung
der Suche aus (per ``ast`` aus backend/main.py geschnitten). Eine Textsuche laese
sonst auch Kommentare mit.

Die Oberflaeche prueft tests/test_support_ibs_skill_ui.js.
"""
import ast
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUELL = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
    print(("  ✓ %s" if cond else "  ✗ %s") % name + ("" if cond or not detail else " – %s" % detail))


def abbruch(text):
    print("ABBRUCH: %s" % text)
    sys.exit(2)


FUNKTIONEN = {n.name: n for n in BAUM.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in ("support_status", "_support_run_query", "_skill_active"):
    if name not in FUNKTIONEN:
        abbruch("Funktion %s nicht in backend/main.py gefunden" % name)


class _Cfg:
    def __init__(self, zustaende):
        self.z = zustaende

    def get_skill_states(self):
        return self.z


class _Antwort:
    def __init__(self, inhalt):
        self.inhalt = inhalt


def status(skill_an, url="https://kv.beispiel.de", key="k"):
    """Fuehrt den echten Status-Endpunkt aus; nur seine Umgebung ist Attrappe."""
    knoten = FUNKTIONEN["support_status"]
    ohne_depends = ast.parse(ast.get_source_segment(QUELL, knoten)
                             .replace("user: str = Depends(require_auth)", "user: str = 'anna'"))
    gefragt = []

    def _skill_active(name):
        gefragt.append(name)
        return skill_an if name == "kundenverwaltung" else False

    umgebung = {
        "config": _Cfg({"jira": {"config": {"ibs_api_url": url, "ibs_api_key": key}}}),
        "_support_jira_limits": lambda cfg: (50, 12),
        "_SUPPORT_FACH": (),
        "_support_cap": lambda wert, vorgabe: vorgabe,
        "_skill_active": _skill_active,
        "JSONResponse": _Antwort,
    }
    exec(compile(ohne_depends, "support_status", "exec"), umgebung)
    return asyncio.run(umgebung["support_status"]()).inhalt, gefragt


print("\n1. Status-Endpunkt")
an, gefragt = status(True)
aus, _ = status(False)
check("Positivkontrolle: der Skill wird abgefragt", "kundenverwaltung" in gefragt, gefragt)
check("Skill an: ibs_active ist wahr", an.get("ibs_active") is True, an)
check("Skill aus: ibs_active ist falsch", aus.get("ibs_active") is False, aus)
check("Konfiguration bleibt davon getrennt gemeldet", aus.get("ibs_configured") is True, aus)
ohne_key, _ = status(True, key="")
check("ohne API-Key: aktiv, aber nicht konfiguriert",
      ohne_key.get("ibs_active") is True and ohne_key.get("ibs_configured") is False, ohne_key)


print("\n2. Suche: die Bedingung vor dem IBS-Aufruf")
# Gesucht wird das If, dessen Rumpf die Kundenverwaltung wirklich anspricht.
treffer = []
for n in ast.walk(FUNKTIONEN["_support_run_query"]):
    if not isinstance(n, ast.If):
        continue
    # Der Aufruf laeuft ueber asyncio.to_thread: der Name steht dort als Argument.
    ruft = any(isinstance(k, ast.Name) and k.id == "tickets_by_buzzwords"
               for b in n.body for k in ast.walk(b))
    if ruft:
        treffer.append(n)
# Das aeusserste If umschliesst alle weiteren.
treffer.sort(key=lambda n: n.lineno)
if not treffer:
    abbruch("kein If mit Aufruf von tickets_by_buzzwords in _support_run_query gefunden")
bedingung = compile(ast.Expression(treffer[0].test), "bedingung", "eval")


def suche_laeuft(body, skill_an):
    return bool(eval(bedingung, {"body": body, "bool": bool,
                                 "_skill_active": lambda n: skill_an and n == "kundenverwaltung"}))


check("Positivkontrolle: Skill an + ibs=true sucht", suche_laeuft({"ibs": True}, True))
check("Skill aus + ibs=true sucht NICHT", not suche_laeuft({"ibs": True}, False))
check("Skill an + ibs=false sucht nicht", not suche_laeuft({"ibs": False}, True))
check("Skill an + Feld fehlt sucht nicht (Vorgabe AUS)", not suche_laeuft({}, True))

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
