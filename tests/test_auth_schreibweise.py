#!/usr/bin/env python3
"""Waechter: der 2FA-Zustand haengt an der PERSON, nicht an der Schreibweise.

Befund Code-Review 2026-10-18: ``auth_state.json`` war nach dem EINGETIPPTEN
Namen geschluesselt. AD nimmt ``alice``, ``firma\\alice`` und
``alice@domaene`` gleichermassen an – mit einer anderen Schreibweise kam man
ohne zweiten Faktor herein, bei Admins richtete die Pflicht-Einrichtung ein
NEUES Secret ein. Zusaetzlich lieferte ein Lesefehler ``{}`` ("niemand hat
2FA"), und geschrieben wurde nicht atomar.

Gemessen an den ECHTEN Funktionen aus main.py (per AST geschnitten, in einem
Wegwerf-Verzeichnis ausgefuehrt, Tresor als Durchreiche):
  [1] Positivkontrolle: Schreiben/Lesen im Sandkasten
  [2] eine Person, drei Schreibweisen -> ein Eintrag
  [3] Altbestand mit mehreren Schreibweisen wird zusammengefuehrt, die aktive
      2FA gewinnt
  [4] atomar + Sicherung .bak, Modus 0600
  [5] fail-closed: kaputte Datei -> Sicherung; beides kaputt -> Ausnahme
  [6] login() faengt die Ausnahme und antwortet 503 (AST)
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"
OK = FAIL = 0


def check(name: str, bed: bool, detail: str = "") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


QUELLE = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
NAMEN = ("_norm_login", "_auth_schluessel", "_auth_eintraege_zusammenfuehren",
         "_auth_state_datei_lesen", "_load_auth_state", "_save_auth_state",
         "_get_user_auth_state", "_set_user_auth_state")
teile = [n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
         and n.name in NAMEN + ("AuthStateUnlesbar",)]
gefunden = sorted(n.name for n in teile)
if sorted(NAMEN + ("AuthStateUnlesbar",)) != gefunden:
    abbruch("Funktionen nicht eindeutig gefunden: %s" % gefunden)

tresor = types.ModuleType("backend.geheimnis_tresor")
tresor.entschluessele_baum = lambda x: x
tresor.verschluessele_baum = lambda x: x
tresor.hauptfernet = lambda: None
tresor.klartext_felder = lambda x: []
paket = types.ModuleType("backend")
paket.geheimnis_tresor = tresor
sys.modules["backend"] = paket
sys.modules["backend.geheimnis_tresor"] = tresor

SANDKASTEN = Path(tempfile.mkdtemp(prefix="auth_schreibweise_"))
DATEI = SANDKASTEN / "auth_state.json"
BAK = SANDKASTEN / "auth_state.json.bak"
ns = {"json": json, "os": os, "Path": Path, "_AUTH_STATE_FILE": DATEI}
modul = ast.Module(body=teile, type_ignores=[])
ast.fix_missing_locations(modul)
try:
    exec(compile(modul, str(MAIN), "exec"), ns)
except Exception as e:  # noqa: BLE001
    abbruch("nicht ausfuehrbar: %r" % e)
if ns["_AUTH_STATE_FILE"].parent != SANDKASTEN:
    abbruch("Zieldatei zeigt aus dem Sandkasten heraus")

get, setz = ns["_get_user_auth_state"], ns["_set_user_auth_state"]
laden, speichern = ns["_load_auth_state"], ns["_save_auth_state"]
Unlesbar = ns["AuthStateUnlesbar"]


def roh():
    return json.loads(DATEI.read_text())


def frisch():
    for p in SANDKASTEN.iterdir():
        p.unlink()


try:
    print("\n[1] Positivkontrolle")
    frisch()
    check("ohne Datei: leerer Bestand (Neuinstallation)", laden() == {})
    setz("jarvis", {"totp_enabled": True, "totp_secret": "S1"})
    check("Schreiben landet in der Sandkasten-Datei", DATEI.exists()
          and roh().get("users", {}).get("jarvis", {}).get("totp_secret") == "S1", str(roh() if DATEI.exists() else None))
    if FAIL:
        abbruch("Messaufbau traegt nicht")

    print("\n[2] Eine Person, drei Schreibweisen")
    frisch()
    setz("FIRMA\\alice", {"totp_enabled": True, "totp_secret": "GEHEIM"})
    for form in ("alice", "Alice", "firma\\alice", "alice@firma.local", " ALICE "):
        st = get(form)
        check("%r sieht die 2FA" % form, st.get("totp_enabled") is True and st.get("totp_secret") == "GEHEIM",
              str(st))
    check("gespeichert unter genau EINEM Schluessel 'alice'", list(roh()["users"]) == ["alice"],
          str(list(roh()["users"])))
    setz("alice@firma.local", {"must_change_password": False})
    check("Schreiben ueber eine andere Schreibweise trifft denselben Eintrag",
          roh()["users"]["alice"].get("totp_secret") == "GEHEIM"
          and roh()["users"]["alice"].get("must_change_password") is False, str(roh()))

    print("\n[3] Altbestand mit mehreren Schreibweisen")
    frisch()
    DATEI.write_text(json.dumps({"users": {
        "alice": {"must_change_password": False, "totp_enabled": False, "totp_secret": None},
        "firma\\alice": {"totp_enabled": True, "totp_secret": "AKTIV", "totp_zurueckgesetzt": None},
        "Bob@firma.local": {"totp_enabled": False, "totp_secret": None},
    }, "docker_password": {"jarvis": "x"}}))
    st = laden()
    check("Lader liefert je Person einen Eintrag", sorted(st["users"]) == ["alice", "bob"], str(sorted(st["users"])))
    check("die AKTIVE 2FA gewinnt (die Migration schaltet nichts ab)",
          st["users"]["alice"].get("totp_enabled") is True and st["users"]["alice"].get("totp_secret") == "AKTIV",
          str(st["users"]["alice"]))
    check("fehlende Felder kommen aus den anderen Eintraegen",
          st["users"]["alice"].get("must_change_password") is False, str(st["users"]["alice"]))
    check("die Datei ist danach zusammengefuehrt zurueckgeschrieben", sorted(roh()["users"]) == ["alice", "bob"],
          str(sorted(roh()["users"])))
    check("fremde Bereiche (docker_password) bleiben", roh().get("docker_password") == {"jarvis": "x"})
    check("get('alice') nach der Migration mit 2FA", get("alice").get("totp_secret") == "AKTIV")

    print("\n[4] Atomar, Sicherung, Modus")
    frisch()
    speichern({"users": {"a": {"n": 1}}})
    speichern({"users": {"a": {"n": 2}}})
    check("Hauptdatei traegt den neuen Stand", roh()["users"]["a"]["n"] == 2)
    check(".bak traegt den vorigen Stand", BAK.exists() and json.loads(BAK.read_text())["users"]["a"]["n"] == 1)
    check("Hauptdatei 0600", stat.S_IMODE(DATEI.stat().st_mode) == 0o600, oct(stat.S_IMODE(DATEI.stat().st_mode)))
    check("keine Temp-Datei bleibt liegen", sorted(p.name for p in SANDKASTEN.iterdir())
          == ["auth_state.json", "auth_state.json.bak"], str(sorted(p.name for p in SANDKASTEN.iterdir())))
    DATEI.write_text("{kaputt")
    speichern({"users": {"a": {"n": 3}}})
    check("kaputte Hauptdatei ueberschreibt die gute Sicherung NICHT",
          json.loads(BAK.read_text())["users"]["a"]["n"] == 1, BAK.read_text()[:80])

    print("\n[5] Fail-closed")
    frisch()
    speichern({"users": {"a": {"totp_enabled": True, "totp_secret": "X"}}})
    speichern({"users": {"a": {"totp_enabled": True, "totp_secret": "Y"}}})
    DATEI.write_text("{halb geschrieben")
    st = laden()
    check("kaputte Datei -> Sicherung wird gelesen (2FA bleibt)",
          st.get("users", {}).get("a", {}).get("totp_secret") == "X", str(st))
    BAK.write_text("auch kaputt")
    try:
        laden()
        wurf = False
    except Unlesbar:
        wurf = True
    except Exception as e:  # noqa: BLE001
        wurf = "andere Ausnahme %r" % e
    check("beides kaputt -> AuthStateUnlesbar (nicht {})", wurf is True, str(wurf))
    try:
        get("a")
        wurf = False
    except Unlesbar:
        wurf = True
    check("auch _get_user_auth_state verweigert statt 'keine 2FA'", wurf is True)
    DATEI.write_text("[]")
    BAK.unlink()
    try:
        laden()
        wurf = False
    except Unlesbar:
        wurf = True
    check("JSON ohne Objekt zaehlt als unlesbar", wurf is True)
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n[6] login() antwortet 503 statt anzumelden")
login = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "login"), None)
if login is None:
    abbruch("login() nicht gefunden")
faenger = [h for t in ast.walk(login) if isinstance(t, ast.Try) for h in t.handlers
           if isinstance(h.type, ast.Name) and h.type.id == "AuthStateUnlesbar"]
ruft = [t for t in ast.walk(login) if isinstance(t, ast.Try)
        and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_login_ablauf"
                for s in t.body for c in ast.walk(s))
        and any(isinstance(h.type, ast.Name) and h.type.id == "AuthStateUnlesbar" for h in t.handlers)]
check("der Aufruf von _login_ablauf steht im try mit AuthStateUnlesbar", len(ruft) == 1)
codes = [k.value for h in faenger for kw in ast.walk(h) if isinstance(kw, ast.keyword)
         and kw.arg == "status_code" for k in [kw.value] if isinstance(k, ast.Constant)]
check("der Faenger antwortet 503", codes == [503], str(codes))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
