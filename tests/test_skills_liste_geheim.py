#!/usr/bin/env python3
"""Waechter: ``GET /api/skills`` gibt keine Skill-Geheimnisse heraus.

Befund (Pentest-Vorbereitung 2026-11-05, auf DEV gemessen): die Skill-Liste
haengt an ``require_auth`` und lieferte ueber ``list_skills()`` die ROHE
Skill-Konfiguration – Jira-/Confluence-``api_token``, Google-``client_secret``,
``ibs_api_key`` im Klartext an jeden angemeldeten Benutzer.

Gemessen wird die WIRKUNG ueber die echte Kette:
  1. ``SkillManager.list_skills`` (echte Methode, Attrappe nur fuer Loader und
     ``backend.config``) mit Zustaenden, die echte Geheimfeldnamen tragen –
     auch verschachtelt und in Listen;
  2. ``secret_reveal.skills_liste_fuer`` fuer Admin und Nicht-Admin;
  3. die Route ``get_skills`` in main.py gibt ihre Antwort ueber genau diese
     Funktion aus, mit ``_user_is_admin(user)`` als Admin-Merkmal (AST).

``backend.config`` wird NIE echt importiert (schreibt sonst die Live-settings).
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import ast
import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}" + (f"  -> {detail}" if detail else ""))


GEHEIM = {
    "api_token": "SONDE-JIRA-TOKEN-1",
    "client_secret": "SONDE-GOOGLE-SECRET-2",
    "ibs_api_key": "SONDE-IBS-KEY-3",
    "bot_token": "SONDE-TELEGRAM-4",
    "hana_password": "SONDE-HANA-5",
    # Chiffrat eines Moduls (Freigaben der Wissensdatenbank): kein Klartext,
    # gehoert aber trotzdem nicht in eine Liste (Live-Probe DEV 2026-11-08).
    "password_enc": "SONDE-MOUNT-CHIFFRAT-6",
}
NICHT_GEHEIM = {"base_url": "https://jira.beispiel.de", "org_field": "customfield_1"}

ZUSTAENDE = {
    "jira": {"enabled": True, "installed": True, "config": {
        **NICHT_GEHEIM, "api_token": GEHEIM["api_token"],
        "ibs_api_key": GEHEIM["ibs_api_key"]}},
    "google": {"enabled": True, "config": {"client_id": "id-1",
                                            "client_secret": GEHEIM["client_secret"]}},
    "telegram": {"enabled": False, "config": {
        "verbindung": {"bot_token": GEHEIM["bot_token"]}}},
    "sap": {"enabled": True, "config": {
        "systeme": [{"name": "P01", "hana_password": GEHEIM["hana_password"]}]}},
    "knowledge": {"enabled": True, "config": {
        "mounts": [{"name": "freigabe1", "username": "leser",
                    "password_enc": GEHEIM["password_enc"]}]}},
}

# ── Attrappe backend.config ─────────────────────────────────────────────
cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return ZUSTAENDE


cfg_mod.config = _Cfg()
sys.modules["backend.config"] = cfg_mod

try:
    from backend.skills import manager as mgr
    from backend import secret_reveal as sr
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Import scheiterte: {e!r}")
    sys.exit(2)

if getattr(mgr, "config", None) is not cfg_mod.config:
    print("ABBRUCH: manager benutzt nicht die Attrappe von backend.config")
    sys.exit(2)


class _Loader:
    loaded_skills = {}

    def discover_skills(self):
        return [{"name": n, "path": f"/opt/x/skills/{n}"} for n in ZUSTAENDE]


sm = object.__new__(mgr.SkillManager)
sm.loader = _Loader()
sm._install_status = {}
sm.missing_for = lambda name, inst: {"pip": [], "apt": [], "commands": []}
sm._installed_packages = lambda: set()

roh = sm.list_skills()

# Positivkontrolle: die Liste ist wirklich ueber die Zustaende gelaufen
namen = sorted(s.get("name") for s in roh)
if namen != sorted(ZUSTAENDE) or not all("config" in s for s in roh):
    print(f"ABBRUCH: list_skills lief nicht ueber die Attrappe ({namen})")
    sys.exit(2)
# Positivkontrolle: ein nicht-geheimer Wert kommt durch (sonst waere "kein
# Geheimnis darin" trivial wahr, weil gar nichts darin ist)
jira = next((s for s in roh if s.get("name") == "jira"), {})
if (jira.get("config") or {}).get("base_url") != NICHT_GEHEIM["base_url"]:
    print("ABBRUCH: Positivkontrolle – nicht-geheimer Wert fehlt in list_skills")
    sys.exit(2)


def enthaelt_geheimnis(obj) -> list:
    text = json.dumps(obj, ensure_ascii=False)
    return [w for w in GEHEIM.values() if w in text]


print("── 1. list_skills selbst ──")
check("list_skills gibt keinen Geheimwert heraus (auch verschachtelt/in Listen)",
      not enthaelt_geheimnis(roh), str(enthaelt_geheimnis(roh)))
check("Geheimfeld bleibt als leerer Schluessel erkennbar (jira.api_token == '')",
      (jira.get("config") or {}).get("api_token") == "")

print("── 2. Antwortform je Rolle ──")
admin = sr.skills_liste_fuer(roh, True)
nutzer = sr.skills_liste_fuer(roh, False)
check("Admin: kein Geheimwert", not enthaelt_geheimnis(admin), str(enthaelt_geheimnis(admin)))
check("Admin: nicht-geheime Konfiguration bleibt",
      any((s.get("config") or {}).get("base_url") == NICHT_GEHEIM["base_url"] for s in admin))
check("Nicht-Admin: kein einziger Eintrag traegt 'config'",
      all("config" not in s for s in nutzer), str([s.get("name") for s in nutzer if "config" in s]))
check("Nicht-Admin: Liste vollstaendig (Sichtbarkeit der Reiter haengt daran)",
      sorted(s.get("name") for s in nutzer) == namen)
check("Nicht-Admin: enabled bleibt erhalten",
      all("enabled" in s for s in nutzer))
# Auch ein ROHER Eintrag (falls jemand list_skills umgeht) wird maskiert
roh_direkt = [{"name": "jira", "config": dict(ZUSTAENDE["jira"]["config"])}]
check("Admin: auch roh uebergebene Konfiguration wird maskiert",
      not enthaelt_geheimnis(sr.skills_liste_fuer(roh_direkt, True)))

print("── 3. Route GET /api/skills ──")
src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(src)
fn = None
for n in ast.walk(baum):
    if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_skills":
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "get"
                    and d.args and isinstance(d.args[0], ast.Constant)
                    and d.args[0].value == "/api/skills"):
                fn = n
if fn is None:
    print("ABBRUCH: Route get_skills nicht gefunden")
    sys.exit(2)
rets = [r for r in ast.walk(fn) if isinstance(r, ast.Return)]
check("genau ein return", len(rets) == 1, str(len(rets)))
ret_ok = False
for r in rets:
    for c in ast.walk(r):
        if (isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "skills_liste_fuer"
                and len(c.args) == 2):
            a0, a1 = c.args
            erstes = (isinstance(a0, ast.Call) and getattr(a0.func, "attr", "") == "list_skills")
            zweites = (isinstance(a1, ast.Call) and getattr(a1.func, "id", "") == "_user_is_admin"
                       and a1.args and getattr(a1.args[0], "id", "") == "user")
            ret_ok = ret_ok or (erstes and zweites)
check("Antwort = skills_liste_fuer(sm.list_skills(), _user_is_admin(user))", ret_ok)

print(f"\nBilanz: {ok} OK, {fail} FAIL")
sys.exit(0 if fail == 0 else 1)
